# -*- coding: utf-8 -*-

import sys, os
sys.path.append(
    os.path.join(os.path.dirname(os.path.realpath(__file__)), os.path.pardir, "src")
)
import optparse
import time
from zfstools.models import Dataset, Pool, Snapshot, PoolSet
from zfstools.connection import ZFSConnection
from zfstools.util import stderr, verbose_stderr, set_verbose

def main():

        #===================== configuration =====================

        parser = optparse.OptionParser("usage: %prog [-k NUMSNAPS] <datasetname>")
        parser.add_option('-k', '--keep', action='store', dest='keep', default=7, help='how many snapshots to keep (default: %default), 0 means delete all')
        parser.add_option('-p', '--prefix', action='store', dest='prefix', default="autosnapshot-", help='prefix to prepend to snapshot names (default: %default)')
        parser.add_option('-P', '--property', action='store', dest='property', help='property (name=value) to apply to snapshots')
        parser.add_option('-v', '--verbose', action='store_true', dest='verbose', default=False, help='be verbose (default: %default)')
        parser.add_option('-t', '--timeformat', action='store', dest='timeformat', default="%Y-%m-%d-%H%M%S", help='postfix time format to append to snapshot names (default: %default, MUST be sortable using a general sort)')
        parser.add_option('--utc', action='store_true', dest='utc', default=False, help='Use UTC for timestamps (default: no)')
        parser.add_option('-n', '--dry-run', action='store_true', dest='dryrun', default=False, help='don\'t actually manipulate any file systems')
        parser.add_option('--nosnapshot', action='store_true', dest='nosnapshot', default=False, help='don\'t create new snapshot, only delete according to keep value (default: %default)')
        parser.add_option('-w', '--warnondestroyfailure', action='store_true', dest='warnondestroyfailure', default=False, help='warn rather than abort on destroy failure (default: %default)')
        parser.epilog =  """The --prefix and --property options are also used (if specified) to filter the snapshots to delete. 
        That is, only those snapshots that start with PREFIX and have a property named NAME with a value of
        VALUE will be considered for deletion."""
        opts,args = parser.parse_args(sys.argv[1:])

        try:
                keep = int(opts.keep)
                assert keep >= 0
        except (ValueError,AssertionError) as e:
                parser.error("keep must be greater than 0")
                sys.exit(os.EX_USAGE)

        if len(args) == 1:
                try: source_host, source_dataset_name = args[0].split(":",1)
                except ValueError: source_host, source_dataset_name = "localhost",args[0]
        else:
                parser.error("arguments are wrong")
                sys.exit(os.EX_USAGE)

        set_verbose(opts.verbose)

        snapshot_prefix = opts.prefix
        snapshot_postfix = lambda: time.strftime(opts.timeformat, time.gmtime() if opts.utc else time.localtime() )

        snapshot_properties = {}

        if opts.property:
                split = opts.property.split('=',1)
                if len(split) != 2:
                        parser.error('--property should be of the form name=value')
                        sys.exit(os.EX_USAGE)
                snapshot_properties[ split[ 0 ] ] = split[ 1 ]

        #===================== end configuration =================

        # ================ start program algorithm ===================

        src_conn = ZFSConnection(source_host,properties=snapshot_properties.keys())
        snapshot_unique_name = snapshot_prefix + snapshot_postfix()
        flt = lambda x: x.name.startswith(snapshot_prefix) and (not snapshot_properties or x.get_property(snapshot_properties.keys()[0])==snapshot_properties.values()[0])

        verbose_stderr("Assessing that the specified dataset exists...")
        try:
                source_dataset = src_conn.pools.lookup(source_dataset_name)
                verbose_stderr("%s: OK" % source_dataset)
        except KeyError:
                verbose_stderr("No.\nError: the source dataset does not exist.  Snapshot cannot continue.")
                sys.exit(2)

        if keep > 0 and not opts.nosnapshot:
                verbose_stderr("Snapshotting dataset %s:%s as %s" % (source_host, source_dataset_name, snapshot_unique_name))

                if not opts.dryrun:
                        src_conn.snapshot_recursively(source_dataset_name, snapshot_unique_name, snapshot_properties)
                        # FIXME: what follows is retarded design
                        src_conn.pools  # trigger update

        ssn = sorted([ (x.get_property('creation'), x.name, x) for x in source_dataset.get_snapshots(flt) ])

        if opts.dryrun and keep > 0 and not opts.nosnapshot:
                # simulate the addition of a new dataset
                keep = keep - 1

        if keep > 0:
                destroy_ssn = ssn[:-keep]
        else:
                destroy_ssn = ssn
        for x in destroy_ssn:
                path = (x[-1].get_path())
                verbose_stderr("Destroying obsolete snapshot: %s" % path)
                if not opts.dryrun:
                        ok = src_conn.destroy_recursively(path, returnok=opts.warnondestroyfailure)
                        if not ok:
                                stderr("Failed to destroy obsolete snapshot: %s" % path)
