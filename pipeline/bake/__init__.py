"""Bake a scanned office floor into the files the floor walkthrough (web/walkthrough/) draws.

    python -m pipeline.bake <scanId> [--property <CoStar id> --floor <n>]

Output (licensed, git-ignored): web/walkthrough/floors/<scanId>/
    raw/     the Matterport response, the MatterPak mesh and textures, the floor plan image (source.py)
    data/    scene.json, mesh binaries and texture atlases, floor and wall images, shell.json, walk.png, band.png
    pano/    2k/ and 4k/ skybox faces, <panoId>_<face>.jpg

The steps follow Pranava's floor 16 build (web/walkthrough/HANDOFF.md, sections 3 and 4).
"""
