# Project-shared namespace (script contract §4): the panel stock and the shelf's
# interface dimensions. Parts read every name as hc.<name>.
PARAMS = {
    "panel_t": Param(18.0, min=12.0, max=25.0, doc="panel stock thickness, mm"),
}

# Shelf envelope.
width = 600.0
depth = 250.0
side_height = 200.0

# Cable pass-through through the deck, on the deck's centre.
cable_bore_dia = 8.0
