def cleanupdict(d):
    clean = {}
    for k, v in d.items():
        if isinstance(v, dict):
            nested = cleanupdict(v)
            if len(nested.keys()) > 0:
                clean[k] = nested
        elif v is not None:
            clean[k] = v
    return clean
