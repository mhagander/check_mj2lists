check_mj2lists
--------------
This is a Nagios plugin to monitor the membership on majordomo2 lists.

It will take a configuration file containing *one or more* list specifications,
and compare the list of members in this configuration file to the list of
members that are actually on the list.

If there are members on the list that aren't listed in the file, the plugin will
signal **CRITICAL** state (and of course list which members are incorrect).

If there are members in the file that aren't subscribed to the list, the plugin
will signal **WARNING** state.

When checking multiple list, the *most severe* result will be returned. The
resulting text output from the different lists will be appended to the complete
output.

Commandline
===========
The plugin should be executed from Nagios with the following syntax::

  check_mj2lists.py -f /path/to/file.ini

Config file
===========
The config file is a standard file parsed by Python's ConfigParser module.
There is one []-section for each list to be checked. Usually the [DEFAULT]
section is used to specify the server and password, but this is not required -
it can be specified for each individual list. A typical file may look something
like this::

  [DEFAULT]
  host=lists.domain.org
  password=supersecret

  [list1]
  members=a@foo.com,b@bar.com,c@baz.com

  [list2]
  members=a@foo.com,c@baz.com
  host=lists.otherdomain.org
  password=evenmoresecret

This will check the membership of list1 on lists.domain.org, whereas list2
will be checked on lists.otherdomain.org.
  
