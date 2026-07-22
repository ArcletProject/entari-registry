import ast
import time
import tempfile
import zipfile
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import httpx2

client = httpx2.Client(follow_redirects=True, verify=False, proxy="http://127.0.0.1:7890")


class PluginRole(Enum):
    NORMAL = "normal"
    """普通插件，适用于大多数场景，具有完整的生命周期和功能支持"""
    UTILITY = "utility"
    """工具插件，适用于提供辅助功能的插件，可能不具有完整的生命周期支持，一般也不会被其他插件直接依赖"""
    LIBRARY = "library"
    """库插件，适用于提供公共功能的插件，通常不具有生命周期支持，但可以被其他插件依赖"""
    COMPLEX = "complex"
    """复杂插件，适用于具有复杂功能和生命周期的插件，可能需要特殊的处理和支持"""


@dataclass
class PluginMetadata:
    name: str
    """插件名称"""
    role: PluginRole = PluginRole.NORMAL
    """插件角色，用于区分插件的功能定位，便于用户理解和管理"""
    author: list[str | dict] = field(default_factory=list)
    """插件作者"""
    version: str | None = None
    """插件版本"""
    license: str | None = None
    """插件许可证"""
    urls: dict[str, str] | None = None
    """插件链接"""
    description: str | None = None
    """插件描述"""
    icon: str | None = None
    """插件图标 URL"""
    readme: str | None = None
    """插件 README"""
    classifier: list[str] = field(default_factory=list)
    """插件分类"""
    requirements: list[str] = field(default_factory=list)
    """插件依赖"""
    depend_services: list[type | str | dict] = field(default_factory=list)
    """插件依赖的服务"""
    config: Any | None = None
    """插件配置模型"""


def metadata(*args, **kwargs):
    return PluginMetadata(*args, **kwargs)


def parse_metadata(content: str) -> PluginMetadata | None:
    nodes = ast.parse(content)
    for node in ast.walk(nodes):
        if isinstance(node, ast.Call):
            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "plugin"
                and node.func.attr == "metadata"
            ):
                node = ast.Call(
                    func=ast.Name(
                        id="metadata",
                        ctx=ast.Load(),
                        lineno=node.func.lineno,
                        col_offset=node.func.col_offset,
                    ),
                    args=node.args,
                    keywords=node.keywords,
                    lineno=node.lineno,
                    col_offset=node.col_offset,
                )
            if isinstance(node.func, ast.Name) and node.func.id == "metadata":
                names = []
                for n in ast.walk(node):
                    if isinstance(n, ast.Name):
                        names.append(n.id)
                ans = eval(
                    compile(ast.Expression(node), filename="<ast>", mode="eval"),
                    {k: object() for k in names} | {"metadata": metadata, "PluginRole": PluginRole},
                )
                return ans
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "PluginMetadata"
        ):
            names = []
            for n in ast.walk(node.value):
                if isinstance(n, ast.Name):
                    names.append(n.id)
            ans = eval(
                compile(ast.Expression(node.value), filename="<ast>", mode="eval"),
                {k: object() for k in names} | {"PluginMetadata": PluginMetadata, "PluginRole": PluginRole},
            )
            return ans


def extract_metadata_from_wheel(
    name: str,
    wheel_url: str,
    sha256: str,
    retries: int = 5,
    chunk_size: int = 64 * 1024,
):
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_file_path = Path(f"{tmp_dir}/{name}")
        tmp = tmp_file_path.with_suffix(".whl.part")
        offset = tmp.stat().st_size if tmp.exists() else 0
        for attempt in range(retries):
            headers = {"Accept-Encoding": "identity"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            try:
                with client.stream("GET", wheel_url, headers=headers, timeout=600) as response:
                    if offset:
                        if response.status_code != 206:
                            offset = 0
                            tmp.unlink(missing_ok=True)
                            continue
                    else:
                        response.raise_for_status()

                    mode = "ab" if offset else "wb"
                    with tmp.open(mode) as tmp_file:
                        for chunk in response.iter_bytes(chunk_size=chunk_size):
                            tmp_file.write(chunk)
                            offset += len(chunk)
                break
            except (
                httpx2.RemoteProtocolError,
                httpx2.ReadTimeout,
                httpx2.ConnectError,
            ):
                if attempt == retries - 1:
                    raise
                time.sleep(0.5 * (attempt + 1))
                offset = tmp.stat().st_size if tmp.exists() else 0
        else:
            raise RuntimeError("Failed to download the wheel after multiple attempts.")
        h = hashlib.sha256()
        with tmp.open("rb") as f:
            while chunk := f.read(chunk_size):
                h.update(chunk)
        if h.hexdigest() != sha256:
            raise ValueError("SHA256 checksum does not match.")

        tmp.replace(tmp_file_path)
        with zipfile.ZipFile(tmp_file_path) as zf:
            names = zf.namelist()
            init_pys = [name for name in names if name.endswith("__init__.py")]
            init_pys.sort(key=lambda x: len(x))
            if init_pys:
                with zf.open(init_pys[0]) as init_file:
                    content = init_file.read().decode("utf-8")
                    return parse_metadata(content)
    return None


def get_package_info(name: str):
    url = f"https://pypi.org/pypi/{name}/json"
    response = client.get(url, timeout=600)
    if response.status_code == 200:
        raw = response.json()
        data = raw["info"]
        urls = raw["urls"]
        print("Downloading wheel for:", name)
        meta = extract_metadata_from_wheel(urls[0]["filename"], urls[0]["url"], urls[0]["digests"]["sha256"])
        print("Fetched package info for:", name)
        return {
            "name": meta.name if meta else data["name"].replace("entari-plugin-", ""),
            "pip_name": data["name"],
            "version": data["version"],
            "description": meta.description if meta and meta.description else data["summary"],
            "authors": str(data["author_email"] or data["author"]).split(","),
            "license": data["license"],
            "homepage": meta.urls["homepage"] if meta and meta.urls else (data["home_page"] or data["project_url"]),
            "tags": data["keywords"].split(", ") if data["keywords"] else [],
            "last_serial": raw["last_serial"],
        }
    return None
