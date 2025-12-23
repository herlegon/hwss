def find_latest_hbase_for_api(
    releases: list,
    api: int = 0,
    major: int = 0
) -> dict[str, str | tuple] | None:
    """
    Find the latest HBase release for a specific API version.

    Args:
        releases: List of release dicts with 'url' and 'version' keys
                  version is (api, bootstrap, (major, minor))
        api: API version to filter by. 0 means latest available API.
        major: Major version to filter by. 0 means latest available Major.

    Returns:
        The latest release dict matching the criteria, or None if not found.
    """
    if not releases:
        return None

    # Helper to extract components for sorting/filtering
    # Returns (api, major, minor, bootstrap)
    def get_components(r):
        v = r['version']
        return (v[0], v[2][0], v[2][1], v[1])

    # Filter by API
    if api != 0:
        releases = [r for r in releases if r['version'][0] == api]
        if not releases:
            return None
    else:
        # Find latest API
        max_api = max(releases, key=lambda r: r['version'][0])['version'][0]
        releases = [r for r in releases if r['version'][0] == max_api]

    # Filter by Major
    if major != 0:
        releases = [r for r in releases if r['version'][2][0] == major]
        if not releases:
            return None
    else:
        # Find latest Major within the filtered releases
        max_major = max(releases, key=lambda r: r['version'][2][0])['version'][2][0]
        releases = [r for r in releases if r['version'][2][0] == max_major]

    # Sort by (api, major, minor, bootstrap) descending.
    # This prioritizes minor version over bootstrap version.
    return max(releases, key=get_components)


# Example usage:
releases = [
    # (api, bootstrap, (major, minor))
    {'version': (1, 1, (1, 10)), 'url': ''},
    {'version': (1, 0, (1, 1)), 'url': ''},
    {'version': (3, 0, (1, 10)), 'url': ''},
    {'version': (3, 0, (1, 12)), 'url': ''},
    {'version': (3, 0, (2, 1)), 'url': ''},
    {'version': (3, 1, (1, 1)), 'url': ''},
    {'version': (3, 1, (2, 15)), 'url': ''},
    {'version': (3, 2, (1, 10)), 'url': ''},
    {'version': (3, 4, (2, 10)), 'url': ''},
    {'version': (3, 4, (2, 50)), 'url': ''},
]

for api in range(4):
    for major in range(3):
        hbase_release = find_latest_hbase_for_api(releases, api=api, major=major)

        if hbase_release is None:
            print(f"Failed to find the latest version for api={api}, major={major}")

        print(f"api={api}, major={major}: {hbase_release}")
    print()

# Now, I want:
# when api=0 -> latest api version
# when major=0 -> latest major version
# other, specified

# api=0, major=0 -> (3, 1, (2, 402))
# api=0, major=1 -> (3, 0, (1, 12))
# api=0, major=2 -> (3, 1, (2, 402))

# api=1, major=0 -> (1, 1, (1, 10))
# api=1, major=1 -> (1, 1, (1, 10))
# api=1, major=2 -> None because major doesn't exist for this api version

# api=2, whatever the major=2 -> None because it doesn't exist

# api=3, major=0 -> (3, 1, (2, 402))
# api=3, major=1 -> (3, 0, (1, 12))
# api=3, major=2 -> (3, 1, (2, 402))

