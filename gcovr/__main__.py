# -*- coding:utf-8 -*-
#
# A report generator for gcov 3.4
#
# This routine generates a format that is similar to the format generated
# by the Python coverage.py module.  This code is similar to the
# data processing performed by lcov's geninfo command.  However, we
# don't worry about parsing the *.gcna files, and backwards compatibility for
# older versions of gcov is not supported.
#
# Outstanding issues
#   - verify that gcov 3.4 or newer is being used
#   - verify support for symbolic links
#
# For documentation, bug reporting, and updates,
# see http://gcovr.com/
#
#  _________________________________________________________________________
#
#  Gcovr: A parsing and reporting tool for gcov
#  Copyright (c) 2013 Sandia Corporation.
#  This software is distributed under the BSD License.
#  Under the terms of Contract DE-AC04-94AL85000 with Sandia Corporation,
#  the U.S. Government retains certain rights in this software.
#  For more information, see the README.md file.
# _________________________________________________________________________
#
# $Revision$
# $Date$
#

import copy
import os
import re
import sys

from optparse import Option, OptionParser, OptionValueError, OptionGroup
from os.path import normpath

from .gcov import get_datafiles, process_existing_gcov_file, process_datafile
from .utils import get_global_stats, build_filter, Logger
from .version import __version__

# generators
from .cobertura_xml_generator import print_xml_report
from .html_generator import print_html_report
from .txt_generator import print_text_report
from .summary_generator import print_summary


#
# Exits with status 2 if below threshold
#
def fail_under(covdata, threshold_line, threshold_branch):
    (lines_total, lines_covered, percent,
        branches_total, branches_covered,
        percent_branches) = get_global_stats(covdata)

    if branches_total == 0:
        percent_branches = 100.0

    if percent < threshold_line and percent_branches < threshold_branch:
        sys.exit(6)
    if percent < threshold_line:
        sys.exit(2)
    if percent_branches < threshold_branch:
        sys.exit(4)


# helper for percentage actions
def check_percentage(option, opt, value):
    try:
        x = float(value)
        if not (0.0 <= x <= 100.0):
            raise ValueError()
    except ValueError:
        raise OptionValueError("option %s: %r not in range [0.0, 100.0]" % (opt, value))
    return x


class PercentageOption (Option):
    TYPES = Option.TYPES + ("percentage",)
    TYPE_CHECKER = copy.copy(Option.TYPE_CHECKER)
    TYPE_CHECKER["percentage"] = check_percentage


def parse_arguments(args):
    """
    Create and parse arguments.
    """
    parser = OptionParser(option_class=PercentageOption)
    parser.usage = "gcovr [options]"
    parser.description = \
        "A utility to run gcov and generate a simple report that summarizes " \
        "the coverage"

    parser.add_option(
        "--version",
        help="Print the version number, then exit",
        action="store_true",
        dest="version",
        default=False
    )
    parser.add_option(
        "-v", "--verbose",
        help="Print progress messages",
        action="store_true",
        dest="verbose",
        default=False
    )
    parser.add_option(
        "--fail-under-line",
        type="percentage",
        metavar="MIN",
        help="Exit with a status of 2 if the total line coverage is less "
             "than MIN. "
             "Can be ORed with exit status of '--fail-under-branch' option",
        action="store",
        dest="fail_under_line",
        default=0.0
    )
    parser.add_option(
        "--fail-under-branch",
        type="percentage",
        metavar="MIN",
        help="Exit with a status of 4 if the total branch coverage is less "
             "than MIN. "
             "Can be ORed with exit status of '--fail-under-line' option",
        action="store",
        dest="fail_under_branch",
        default=0.0
    )


    output_options = OptionGroup(parser, "Output Options")
    output_options.add_option(
        "-o", "--output",
        help="Print output to this filename",
        action="store",
        dest="output",
        default=None
    )
    output_options.add_option(
        "-b", "--branches",
        help="Tabulate the branch coverage instead of the line coverage.",
        action="store_true",
        dest="show_branch",
        default=None
    )
    output_options.add_option(
        "-u", "--sort-uncovered",
        help="Sort entries by increasing number of uncovered lines.",
        action="store_true",
        dest="sort_uncovered",
        default=None
    )
    output_options.add_option(
        "-p", "--sort-percentage",
        help="Sort entries by decreasing percentage of covered lines.",
        action="store_true",
        dest="sort_percent",
        default=None
    )
    output_options.add_option(
        "-s", "--print-summary",
        help="Prints a small report to stdout with line & branch "
             "percentage coverage",
        action="store_true",
        dest="print_summary",
        default=False
    )
    output_options.add_option(
        "-x", "--xml",
        help="Generate XML instead of the normal tabular output.",
        action="store_true",
        dest="xml",
        default=False
    )
    output_options.add_option(
        "--xml-pretty",
        help="Generate pretty XML instead of the normal dense format.",
        action="store_true",
        dest="prettyxml",
        default=False
    )
    output_options.add_option(
        "--html",
        help="Generate HTML instead of the normal tabular output.",
        action="store_true",
        dest="html",
        default=False
    )
    output_options.add_option(
        "--html-details",
        help="Generate HTML output for source file coverage.",
        action="store_true",
        dest="html_details",
        default=False
    )
    output_options.add_option(
        "--html-absolute-paths",
        help="Set the paths in the HTML report to be absolute instead "
             "of relative",
        action="store_false",
        dest="relative_anchors",
        default=True
    )
    output_options.add_option(
        '--html-encoding',
        help='HTML file encoding (default: UTF-8).',
        action='store',
        dest='html_encoding',
        default='UTF-8'
    )
    parser.add_option_group(output_options)

    filter_options = OptionGroup(parser, "Filter Options")
    filter_options.add_option(
        "-r", "--root",
        help="Defines the root directory for source files.  "
             "This is also used to filter the files, and to standardize "
             "the output.",
        action="store",
        dest="root",
        default='.'
    )
    filter_options.add_option(
        "-f", "--filter",
        help="Keep only the data files that match this regular expression",
        action="append",
        dest="filter",
        default=[]
    )
    filter_options.add_option(
        "-e", "--exclude",
        help="Exclude data files that match this regular expression",
        action="append",
        dest="exclude",
        default=[]
    )
    filter_options.add_option(
        "--gcov-filter",
        help="Keep only gcov data files that match this regular expression",
        action="store",
        dest="gcov_filter",
        default=None
    )
    filter_options.add_option(
        "--gcov-exclude",
        help="Exclude gcov data files that match this regular expression",
        action="append",
        dest="gcov_exclude",
        default=[]
    )
    filter_options.add_option(
        "--exclude-directories",
        help="Exclude directories from search path that match this regular expression",
        action="append",
        dest="exclude_dirs",
        default=[]
    )
    parser.add_option_group(filter_options)

    gcov_options = OptionGroup(parser, "GCOV Options")
    gcov_options.add_option(
        "--gcov-executable",
        help="Defines the name/path to the gcov executable [defaults to the "
             "GCOV environment variable, if present; else 'gcov'].",
        action="store",
        dest="gcov_cmd",
        default=os.environ.get('GCOV', 'gcov')
    )
    gcov_options.add_option(
        "--exclude-unreachable-branches",
        help="Exclude from coverage branches which are marked to be excluded "
             "by LCOV/GCOV markers or are determined to be from lines "
             "containing only compiler-generated \"dead\" code.",
        action="store_true",
        dest="exclude_unreachable_branches",
        default=False
    )
    gcov_options.add_option(
        "-g", "--use-gcov-files",
        help="Use preprocessed gcov files for analysis.",
        action="store_true",
        dest="gcov_files",
        default=False
    )
    gcov_options.add_option(
        '--gcov-ignore-parse-errors',
        help="Skip lines with parse errors in GCOV files "
             "instead of exiting with an error. "
             "A report will be shown on stderr.",
        action="store_true",
        dest="gcov_ignore_parse_errors",
        default=False
    )
    gcov_options.add_option(
        '--object-directory',
        help="Specify the directory that contains the gcov data files.  gcovr "
             "must be able to identify the path between the *.gcda files and the "
             "directory where gcc was originally run.  Normally, gcovr can guess "
             "correctly.  This option overrides gcovr's normal path detection and "
             "can specify either the path from gcc to the gcda file (i.e. what "
             "was passed to gcc's '-o' option), or the path from the gcda file to "
             "gcc's original working directory.",
        action="store",
        dest="objdir",
        default=None
    )
    gcov_options.add_option(
        "-k", "--keep",
        help="Keep the temporary *.gcov files generated by gcov.  "
             "By default, these are deleted.",
        action="store_true",
        dest="keep",
        default=False
    )
    gcov_options.add_option(
        "-d", "--delete",
        help="Delete the coverage files after they are processed.  "
             "These are generated by the users's program, and by default gcovr "
             "does not remove these files.",
        action="store_true",
        dest="delete",
        default=False
    )
    parser.add_option_group(gcov_options)

    return parser.parse_args(args=args)


def main(args=None):
    global options
    options, args = parse_arguments(args)

    logger = Logger(options.verbose)

    if options.version:
        logger.msg(
            "gcovr {version}\n"
            "\n"
            "Copyright (2013) Sandia Corporation. Under the terms of Contract\n"
            "DE-AC04-94AL85000 with Sandia Corporation, the U.S. Government\n"
            "retains certain rights in this software.",
            version=__version__)
        sys.exit(0)

    if options.output is not None:
        options.output = os.path.abspath(options.output)

    if options.objdir is not None:
        if not options.objdir:
            logger.error(
                "empty --object-directory option.\n"
                "\tThis option specifies the path to the object file "
                "directory of your project.\n"
                "\tThis option cannot be an empty string.")
            sys.exit(1)
        tmp = options.objdir.replace('/', os.sep).replace('\\', os.sep)
        while os.sep + os.sep in tmp:
            tmp = tmp.replace(os.sep + os.sep, os.sep)
        if normpath(options.objdir) != tmp:
            logger.warn(
                "relative referencing in --object-directory.\n"
                "\tthis could cause strange errors when gcovr attempts to\n"
                "\tidentify the original gcc working directory.")
        if not os.path.exists(normpath(options.objdir)):
            logger.error(
                "Bad --object-directory option.\n"
                "\tThe specified directory does not exist.")
            sys.exit(1)

    options.starting_dir = os.path.abspath(os.getcwd())
    if not options.root:
        logger.error(
            "empty --root option.\n"
            "\tRoot specifies the path to the root "
            "directory of your project.\n"
            "\tThis option cannot be an empty string.")
        sys.exit(1)
    options.root_dir = os.path.abspath(options.root)

    #
    # Setup filters
    #

    for i in range(0, len(options.exclude)):
        options.exclude[i] = build_filter(options.exclude[i])

    if options.exclude_dirs is not None:
        for i in range(0, len(options.exclude_dirs)):
            options.exclude_dirs[i] = build_filter(options.exclude_dirs[i])

    options.root_filter = re.compile(re.escape(options.root_dir + os.sep))
    for i in range(0, len(options.filter)):
        options.filter[i] = build_filter(options.filter[i])
    if len(options.filter) == 0:
        options.filter.append(options.root_filter)

    for i in range(0, len(options.gcov_exclude)):
        options.gcov_exclude[i] = build_filter(options.gcov_exclude[i])
    if options.gcov_filter is not None:
        options.gcov_filter = build_filter(options.gcov_filter)
    else:
        options.gcov_filter = re.compile('')

    # Get data files
    if len(args) == 0:
        search_paths = [options.root]

        if options.objdir is not None:
            search_paths.append(options.objdir)

        datafiles = get_datafiles(search_paths, options)
    else:
        datafiles = get_datafiles(args, options)

    # Get coverage data
    covdata = {}
    for file_ in datafiles:
        if options.gcov_files:
            process_existing_gcov_file(file_, covdata, options)
        else:
            process_datafile(file_, covdata, options)
    logger.verbose_msg("Gathered coveraged data for {} files", len(covdata))

    # Print report
    if options.xml or options.prettyxml:
        print_xml_report(covdata, options)
    elif options.html or options.html_details:
        print_html_report(covdata, options)
    else:
        print_text_report(covdata, options)

    if options.print_summary:
        print_summary(covdata, options)

    if options.fail_under_line > 0.0 or options.fail_under_branch > 0.0:
        fail_under(covdata, options.fail_under_line, options.fail_under_branch)


if __name__ == '__main__':
    main()