"""Normalize legacy and multiple force-subscription targets without network I/O."""
import re


def parse_subscription_targets(value) -> list[int | str]:
    if value is None or value == '':
        return []
    if isinstance(value, str):
        items = [part for part in re.split(r'[,\s]+', value.strip()) if part]
    elif isinstance(value, int) and not isinstance(value, bool):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = value
    else:
        raise ValueError('Use comma-separated chat IDs or @usernames.')

    result = []
    for item in items:
        if isinstance(item, int) and not isinstance(item, bool):
            # MongoDB decodes large Telegram IDs as bson.int64.Int64.
            target = int(item)
        elif isinstance(item, str):
            item = item.strip()
            if re.fullmatch(r'-?[0-9]+', item):
                target = int(item)
            elif re.fullmatch(r'@?[A-Za-z][A-Za-z0-9_]{0,31}', item):
                target = '@' + item.lstrip('@').lower()
            else:
                raise ValueError('Use comma-separated chat IDs or @usernames.')
        else:
            raise ValueError('Use comma-separated chat IDs or @usernames.')
        if target != 0 and target not in result:
            result.append(target)
    return result
