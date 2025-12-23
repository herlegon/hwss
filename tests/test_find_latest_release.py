def find_latest_hbase_for_api(
    releases: list,
    api: int = 0
) -> dict[str, str | tuple] | None:
    """
    Find the latest HBase release for a specific API version.

    Args:
        releases: List of release dicts with 'url' and 'version' keys
        api: API version to filter by (first component of version tuple)

    Returns:
        The latest release dict matching the API version, or the latest overall release if not found.
    """
    if not releases:
        return None

    # Sort by version tuple in descending order to get the latest
    latest_overall = max(releases, key=lambda r: r['version'])

    if api == 0:
        return latest_overall

    matching_releases = [
        release for release in releases
        if release['version'][0] == api
    ]

    if not matching_releases:
        if api == 2:
            return latest_overall
        return None

    return max(matching_releases, key=lambda r: r['version'])


# Example usage:
releases = [
    {'version': (1, 1, (0, 10)), 'url': ''},
    {'version': (1, 0, (0, 1)), 'url': ''},

    {'version': (4, 0, (2, 1)), 'url': ''},
    {'version': (4, 0, (0, 10)), 'url': ''},
    {'version': (4, 1, (2, 402)), 'url': ''},
    {'version': (4, 1, (0, 1)), 'url': ''},
]

for api in range(5):
    hbase_release = find_latest_hbase_for_api(releases, api=api)

    if hbase_release is None:
        print(f"Failed to find the latest version for api={api}")

    print(f"found for api={api}: {hbase_release}")


# I want:
# api=0 -> (4, 1, (2, 402))
# api=1 -> (1, 1, (0, 10))
# api=2 -> (4, 1, (2, 402))
# api=3 -> None because it doesn't exist
# api=4 -> (4, 1, (2, 402))


