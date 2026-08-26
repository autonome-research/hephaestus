# Project-shared namespace (script contract §4): the vendor flange's interface
# facts, as the gauge part reads them. The vendor solid itself lives in
# imports/flange.step and is the term the edit starts from (INGEST.md §1).
PARAMS = {
    "flange_t": Param(8.0, min=6.0, max=12.0, doc="vendor flange thickness, mm"),
}

# Vendor flange envelope (Ø80 disc), read from parts as hc.<name>.
flange_od = 80.0
