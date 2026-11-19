def validate_threshold(threshold: int) -> int:
    if type(threshold) is not int:
        raise ValueError('threshold must be an integer')
    return threshold


def meets_threshold(value: int, threshold: int) -> bool:
    return value >= threshold
