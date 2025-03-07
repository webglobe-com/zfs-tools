# zflock - advisory locking for ZFS filesystems, using flock on a parallel directory tree.
#
# The parameter filesystem is not validated to be a real ZFS filesystem,
# since we choose not to care if the user locks a non-existent filesystem.
#
# Author: Simon Guest, 22/9/2017
# Licensed under GNU General Public License GPLv3

import fcntl
import optparse
import os
import os.path
import platform
import subprocess
import sys
import time
import traceback
from zfstools.util import stderr, verbose_stderr, set_verbose

LOCKDIR = "/var/lib/zfs-tools/zflock"

def die(message):
    stderr("zflock: %s" % message)
    sys.exit(1)

def lockpath_for(filesystem):
    if os.path.isabs(filesystem):
        die("invalid filesystem (absolute path): %s" % filesystem)
    return os.path.join(LOCKDIR, filesystem)

def readme_for(lockpath):
    return os.path.join(lockpath, "README")

def readme_comment(readme, prefix):
    try:
        with open(readme, "r") as f:
            comment = "%s%s" % (prefix, f.read().rstrip("\n"))
    except IOError:
        comment = ""
    return comment

def print_failure(message):
    stderr("zflock: %s on %s" % (message, platform.node()))

def print_verbose(message):
    verbose_stderr("zflock: %s on %s" % (message, platform.node()))

def lock_and_run(filesystem, command, options):
    """Attempt to lock filesystem and run command, return whether we did."""
    ok = True
    locked = False
    lockpath = lockpath_for(filesystem)
    try:
        os.makedirs(lockpath, 0o0755)
    except os.error:
        pass
    readme = readme_for(lockpath)
    x = os.open(lockpath, os.O_RDONLY)
    if x != -1:
        try:
            fcntl.flock(x, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except IOError:
            print_failure("failed to lock %s%s" % (filesystem, readme_comment(readme, " # ")))
            ok = False
        if ok:
            locked = True
            if options.comment:
                # write a comment if we can
                try:
                    with open(readme, "w") as f:
                        f.write("%s\n" % options.comment)
                except:
                    print_failure("failed to write README for %s" % filesystem)
                    ok = False
        if ok:
            print_verbose("locked %s" % filesystem)
            ok = subprocess.call(command) == 0
            if not ok:
                print_failure("non-zero exit status from %s" % ' '.join(command))
        os.close(x)
        if locked:
            print_verbose("unlocked %s" % filesystem)
    else:
        print_failure("failed to open %s" % lockpath)
        ok = False
    return ok

def list_locks(options):
    for (dirpath, dirnames, filenames) in os.walk(LOCKDIR):
        for d in dirnames:
            lockpath = os.path.join(dirpath, d)
            filesystem = os.path.relpath(lockpath, LOCKDIR)
            try:
                x = os.open(lockpath, os.O_RDONLY)
                if x != -1:
                    fcntl.flock(x, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    # successfully locked, so wasn't locked
                    fcntl.flock(x, fcntl.LOCK_UN)
            except IOError:
                # failed to acquire lock, so must have been locked
                print("%s%s" % (filesystem, readme_comment(readme_for(lockpath), " # ")))
    return True

def gc_locks(options):
    for (dirpath, dirnames, filenames) in os.walk(LOCKDIR, topdown=False):
        for d in dirnames:
            lockpath = os.path.join(dirpath, d)
            filesystem = os.path.relpath(lockpath, LOCKDIR)
            try:
                x = os.open(lockpath, os.O_RDONLY)
                if x != -1:
                    fcntl.flock(x, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    # successfully locked, so wasn't locked
                    try:
                        os.remove(readme_for(lockpath))
                    except OSError:
                        pass
                    try:
                        os.rmdir(lockpath)
                        print_verbose("removed %s" % lockpath)
                    except:
                        pass
                    fcntl.flock(x, fcntl.LOCK_UN)
            except IOError:
                # failed to acquire lock, so must have been locked
                print_verbose("not removing %s%s" % (filesystem, readme_comment(readme_for(lockpath), " # ")))
    return True

def main():
    usage = "usage: %prog [options] [<filesystem> <command>]"
    parser = optparse.OptionParser(usage)
    parser.add_option("-l", "--list", action="store_true", dest="list", default=False, help="list locks, do nothing else (default: %default)")
    parser.add_option("-g", "--gc", action="store_true", dest="gc", default=False, help="garbage collect, do nothing else (default: %default)")
    parser.add_option("-c", "--comment", action="store", dest="comment", default=None, help="comment explaining reason for lock (default: %default)")
    parser.add_option("-v", "--verbose", action="store_true", dest="verbose", default=False, help="be verbose (default: %default)")
    (options, args) = parser.parse_args(sys.argv)

    set_verbose(options.verbose)

    ok = False
    try:
        if options.list:
            if len(args) == 1:
                ok = list_locks(options)
        elif options.gc:
            if len(args) == 1:
                ok = gc_locks(options)
        elif len(args) >= 3:
            ok = lock_and_run(args[1], args[2:], options)
        else:
            parser.print_usage()
            ok = True
    except Exception as e:
        # report exception and exit
        print_failure("failed with exception %s" % e)
        exctype, value, tb = sys.exc_info()
        traceback.print_tb(tb)
        sys.exit(1)

    if not ok:
        sys.exit(1)
