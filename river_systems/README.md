# River system networks

Each file here is the routing network the model uses for one river system: `<system>-network.json` (`murrumbidgee`, `lachlan`, `lower_darling`, `murray`, `goulburn_broken`). It is the same format the page's routing editor exports, so updating a network is:

1. Open the page, **Routing → Edit**, pick the river system and make your changes.
2. **Export draft**. It downloads as `<system>-network.json`.
3. Replace the file here with it, then run `python main.py` to rerun the model and rebuild the page.

The editor starts from the network in these files, so each draft builds on the last.

A file sets every river node's position, runoff share, outlet flag and connection, and the length of every reach that was moved, joined or reshaped. It can also add nodes (junctions, tributaries), delete nodes (`redirects`, `folded`) and move a basin's flow reporting to another node (`reports`). `3_routing/nodes.py` (`apply_network`) checks the file against the network derived from HydroBASINS and the mapped rivers. It refuses a file that names nodes the network no longer has (export it again from the current page), changes a basin's total runoff share, or leaves a basin with no node reporting its flow.

`python 3_routing/export_networks.py` writes the current network of any system that has no file here; `--force` rewrites them all from HydroBASINS and the mapped rivers, discarding the edits.
