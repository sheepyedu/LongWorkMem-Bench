"""Scope recorded by the service desk for revising an existing receipt."""
def authorized(key, prior, proposed, approval):
    return (key == ("A", "0017", 3) and approval == "OPS-42"
            and prior[0] != proposed[0] and prior[1] == proposed[1])
