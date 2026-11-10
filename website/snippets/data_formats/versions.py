from pyfect import semver, semver_range
from pyfect.result import Err

version = semver.parse_unsafe("1.2.3-rc.1+build.5")
print(version.prerelease, version.build)
print(version.bump("minor").format(), version.bump("prerelease").format())
assert version < semver.parse_unsafe("1.2.3")

# A pre-release comes before its release; build metadata doesn't count.
print(sorted(["1.10.0", "1.2.0", "1.2.0-alpha"], key=semver.parse_unsafe))
print(version.difference(semver.parse_unsafe("2.0.0")))

match semver.parse("1.2"):
    case Err(error):
        print(error.message)
    case _:
        raise AssertionError("1.2 is not a version")

supported = semver_range.parse_unsafe("^1.2.3 || >=3")
print(supported.matches("1.9.0"), supported.matches("2.1.0"))
best = supported.max_satisfying(["1.2.0", "1.4.1", "2.0.0"])
print(best)
assert best == semver.parse_unsafe("1.4.1")

# A pre-release matches only a bound on the same version, unless asked.
print(supported.matches("1.5.0-beta"), supported.matches("1.5.0-beta", include_prerelease=True))
print(semver_range.tilde("1.2.3").format())
