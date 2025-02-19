#!/usr/bin/env python
import os.path
import subprocess
import sys
import argparse

from packaging.version import Version

parser = argparse.ArgumentParser()
parser.add_argument('dir', help='directory with versioned folders')
parser.add_argument('infile', help='the file to analyze')
parser.add_argument('repo', nargs='?', default=None, help='the git repository (for sorting commit hashes)')
parser.add_argument('--compare', action='store_true', help='compare output and only show when changed')
parser.add_argument('--verbose', action='store_true', help='verbose output for debugging')
parser.add_argument('--debug', action='store_true', help='passed through to binary if supported')
parser.add_argument('--debug-warnings', action='store_true', help='passed through to binary if supported')
parser.add_argument('--check-library', action='store_true', help='passed through to binary if supported')
parser.add_argument('--timeout', type=int, default=2, help='the amount of seconds to wait for the analysis to finish')
parser.add_argument('--compact', action='store_true', help='only print versions with changes with --compare')
args = parser.parse_args()

def sort_commit_hashes(commits):
    git_cmd = 'git rev-list --abbrev-commit --topo-order --no-walk=sorted --reverse ' + ' '.join(commits)
    p = subprocess.Popen(git_cmd.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=git_repo, universal_newlines=True)
    stdout, stderr = p.communicate()
    if p.returncode != 0:
        print('error: sorting commit hashes failed')
        print(stderr)
        sys.exit(1)
    return stdout.splitlines()

verbose = args.verbose
do_compare = args.compare
if args.compact:
    if not do_compare:
        print('error: --compact requires --compare')
        sys.exit(1)

directory = args.dir
input_file = args.infile
git_repo = args.repo

use_hashes = None
versions = []

for filename in os.listdir(directory):
    f = os.path.join(directory, filename)
    if not os.path.isdir(f):
        continue
    versions.append(filename)

if not len(versions):
    print("error: no versions found in '{}'".format(directory))
    sys.exit(1)

if verbose:
    print("found {} versions in '{}'".format(len(versions), directory))

try:
    Version(versions[0])
    use_hashes = False
    versions.sort(key=Version)
except:
    if verbose:
        print("'{}' not a version - assuming commit hashes".format(versions[0]))
    if not git_repo:
        print('error: git repository argument required for commit hash sorting')
        sys.exit(1)
    if verbose:
        print("using git repository '{}' to sort commit hashes".format(git_repo))
    use_hashes = True
    # if you use the folder from the bisect script that contains the repo as a folder - so remove it from the list
    if versions.count('cppcheck'):
        versions.remove('cppcheck')
    len_in = len(versions)
    versions = sort_commit_hashes(versions)
    if len(versions) != len_in:
        print('error: unexpected amount of versions after commit hash sorting')
        sys.exit(1)

if verbose:
    print("analyzing '{}'".format(input_file))

last_ec = None
last_out = None

for entry in versions:
    exe_path = os.path.join(directory, entry)
    exe = os.path.join(exe_path, 'cppcheck')

    if not use_hashes:
        version = entry
    else:
        # get version string
        version_cmd = exe + ' ' + '--version'
        version = subprocess.Popen(version_cmd.split(), stdout=subprocess.PIPE, universal_newlines=True).stdout.read().strip()
        # sanitize version
        version = version.replace('Cppcheck ', '').replace(' dev', '')

    cmd = exe
    cmd += ' '
    if do_compare:
        cmd += ' -q '
    if args.debug and Version(version) >= Version('1.45'):
        cmd += '--debug '
    if args.debug_warnings and Version(version) >= Version('1.45'):
        cmd += '--debug-warnings '
    if args.check_library and Version(version) >= Version('1.61'):
        cmd += '--check-library '
    if Version(version) >= Version('1.39'):
        cmd += '--enable=all '
    if Version(version) >= Version('1.40'):
        cmd += '--inline-suppr '
    if Version(version) >= Version('1.48'):
        cmd += '--suppress=missingInclude --suppress=missingIncludeSystem --suppress=unmatchedSuppression --suppress=unusedFunction '
    if Version(version) >= Version('1.49'):
        cmd += '--inconclusive '
    cmd += input_file
    if verbose:
        print("running '{}'". format(cmd))
    p = subprocess.Popen(cmd.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=exe_path, universal_newlines=True)
    try:
        comm = p.communicate(timeout=args.timeout)
        out = comm[0] + '\n' + comm[1]
    except subprocess.TimeoutExpired:
        out = "timeout"
        p.kill()
        comm = p.communicate()

    ec = p.returncode

    if not do_compare:
        if not use_hashes:
            print(version)
        else:
            print('{} ({})'.format(entry, version))
        print(ec)
        print(out)
        continue

    # filter out some false positives
    # [*]: (information) Unmatched suppression: missingInclude
    # [*]: (information) Unmatched suppression: missingIncludeSystem
    # [*]: (information) Unmatched suppression: unmatchedSuppression
    # [*]: (information) Unmatched suppression: unusedFunction
    if not use_hashes and (Version(version) >= Version('1.48') or Version(version) <= Version('1.49')):
        lines = out.splitlines()
        out = ""
        for line in lines:
            if line.startswith('[*]: (information) Unmatched suppression:'):
                continue
            out += line + '\n'

    out = out.strip()

    if last_ec is None:
        # first run - only print version
        if not use_hashes:
            print(version)
        else:
            print('{} ({})'.format(entry, version))

        last_ec = ec
        last_out = out
        continue

    do_print = False

    if last_ec != ec:
        if verbose:
            print("{}: exitcode changed".format(version))
        do_print = True

    if last_out != out:
        if verbose:
            print("{}: output changed".format(version))
        do_print = True

    if do_print:
        print(last_ec)
        print(last_out)

    # do not print intermediate versions with --compact
    if not args.compact or do_print:
        if not use_hashes:
            print(version)
        else:
            print('{} ({})'.format(entry, version))

    last_ec = ec
    last_out = out

if do_compare:
    print(last_ec)
    print(last_out)

if verbose:
    print('done')