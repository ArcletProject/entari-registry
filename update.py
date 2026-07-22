import json
import xmlrpc.client

from utils import get_package_info


SERVER = xmlrpc.client.ServerProxy("https://pypi.org/pypi")


def main():
    with open("registry.json", "r", encoding="utf-8") as f:
        registry = json.load(f)
    last_serial = registry["serial"]
    changes = SERVER.changelog_since_serial(last_serial)
    max_serial = last_serial
    touched = set()

    for name, version, ts, action, serial in changes:  # type: ignore
        max_serial = max(max_serial, serial)
        if name.startswith("entari-plugin-"):
            touched.add(name)

    if touched:
        print("Changed:", touched)
    else:
        print("No changes detected.")

    for pkg in touched:
        info = get_package_info(pkg)
        if not info:
            print("Package not found:", pkg)
            registry["plugins"].pop(pkg, None)
        else:
            registry["plugins"][pkg] = info

    registry["serial"] = max_serial

    with open("registry.json", "w+", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
