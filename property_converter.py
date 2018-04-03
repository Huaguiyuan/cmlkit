
def convert(data, prop, origin, target):
    if origin == target:
        return prop
    else:
        if data.family == 'kaggle':
            if target == 'fe':
                if origin == 'fec':
                    assert 'n_atoms' in data.p
                    return prop / data.p['n_atoms']
                if origin == 'fecreal':
                    assert 'n_sub' in data.p
                    return prop / data.p['n_sub']
                if origin == 'fepa':
                    assert 'n_atoms' in data.p
                    assert 'n_sub' in data.p
                    return prop * data.p['n_atoms'] / data.p['n_sub']
                else:
                    raise Exception("Can't convert %s to %s" % (origin, target))

            elif target == 'fsb':
                return prop
            else:
                raise Exception("Can't convert %s to %s" % (origin, target))
        else:
            raise Exception(data.name)