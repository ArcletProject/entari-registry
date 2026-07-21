import json
from selectolax.lexbor import LexborHTMLParser

from utils import client, get_package_info


def main():
    html = client.get("https://pypi.org/simple", timeout=600)
    html.raise_for_status()
    serial = int(html.headers["X-PyPI-Last-Serial"])
    print("Simple index fetched, serial:", serial)
    tree = LexborHTMLParser(html.text)

    plugins = []

    for node in tree.css('a'):
        name = node.text()
        if name.startswith('entari-plugin'):
            plugins.append(name)

    registry = {
        "serial": serial,
        "plugins": {}
    }

    for pkg in plugins:
        info = get_package_info(pkg)
        if info:
            registry["plugins"][pkg] = info
        else:
            print("Package not found:", pkg)

    with open("registry.json", "w+", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
