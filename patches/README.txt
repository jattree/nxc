.nxc patches, approved set
==========================

Each .nxc here turns one original ZX Spectrum game file into a Spectrum Next
version. Most remove the colour clash, drawing the moving figures with the
Next's hardware sprites or Layer 2 so they keep their own colours. Games with
no clash to remove keep their original look and gain the menu, cheats and a
clean Next start-up. Many also offer Enhanced colours, off by default. Each
has a .nfo beside it with the details: the exact game file it needs, what it
changes, its cheats, credits, known issues and how it was tested.

The patches carry none of the games' code. You need your own copy of each
game: the exact dump whose MD5 its .nfo gives, under any name. A few games
load from their tape files (.tap or .tzx); their .nfo names every file.

On the Next
-----------
1. Set up the card once: run tools/setup_card.py from the nxc repo with the
   card's top folder, or copy the repo's sdcard/ folder to the card and add
   the .nxc line to nextzxos/browser.cfg (README.md, "One-time card setup").
2. Copy a game's folder to the card's nxc folder and put your game file in
   it, beside the .nxc.
3. Choose the .nxc in the Browser. A menu shows the cheats and options;
   ENTER rebuilds the game ("Patching..." flashes) and runs it.

Each game has its own folder. Patch names follow the game file's name, with
.nxc in place of .z80. Where two patches share one game, they share its folder
and a tag in brackets tells them apart.

Credits
-------
Built with NexClash by Dean Woodyatt (Bleugh.biz), GPL-3.0-or-later. Patches by
the people named in each .nfo. The games belong to their original authors and
publishers.

Status
------
Tested in the JNext emulator; the loader has also run on a NextNano (Tang Nano
20K build of the Next). Not yet run on an official Next. See each .nfo.
