#!/usr/bin/python3

import os
import apt
os.chdir("usr/share/linuxmint/mintinstall/categories")


c = apt.Cache()

for file in os.listdir():
    new = []
    with open(os.path.join(os.getcwd(), file)) as f:
        for line in f:
            if line.startswith("flatpak:"):
                new.append(line)
                continue
            if line == "\n":
                new.append(line)
                continue
            try:
                pkg = c[line.rstrip()]
                new.append(line)
            except KeyError as e:
                print(f"missing {line}", end="")
    with open(os.path.join(os.getcwd(), file), "w") as f:
        f.write("".join(new))
