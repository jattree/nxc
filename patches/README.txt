.nxc patches, approved set
==========================

Each .nxc here turns one original ZX Spectrum game file into a Spectrum Next
version with the colour clash removed: the moving figures become hardware
sprites. Each has a .nfo beside it with the details: the exact game file it
needs, what it changes, its cheats, credits and how it was tested.

The patches carry none of the games' code. You need your own copy of each
game, with exactly the file name and MD5 given in its .nfo.

On the Next
-----------
1. Install the loader once: NEXCLASH in C:/DOT/, NXCHAND.BAS in C:/NEXTZXOS/,
   and the .nxc line in C:/NEXTZXOS/BROWSER.CFG (see the nxc repo's
   firmware/README.md).
2. Copy a game's folder to the card and put your game file in it, beside
   the .nxc.
3. Choose the .nxc in the Browser. A menu shows the cheats and colour sets;
   ENTER builds the game and runs it.

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
Tested in the JNext emulator only. See each .nfo for what was checked.
