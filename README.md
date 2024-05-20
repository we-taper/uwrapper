# Unison Wrapper

Aims to manage the archive files created by Unison.

**Problem.**

Unison use archive files to store information about a synchronisation. These files exist on both roots. Using for a long time creates a significant amount of archive files, resulting in confusion and a cluttered `~/.unison` folder.

**Archive files**

Brief note: Assume there are two roots: A and B, there will be two archive files for A, located on A's machine's `~/.unison` folder, and named `arX` and `fpX`, where `X` is a 32 length 32 alphanumeric in lower case. Similarly, for `B`, we have two archive files located similarly.

The names of roots are canonized, and used to compute name of the archive files, i.e., the `X` above. Note that the name of a root contains both a hostname and the full path. On both the local machine and the remote, the hostname is first determined by the environment variable `UNISONLOCALHOSTNAME`

See Appendix for the full documentation.

**Solution**

We create an equivalent relation between a folder and a profile file. The profile file conforms to unison's specification, and has a `.prf` extension. The profile file exists inside the folder. Besides the profile file, the folder stores the archive files corresponding to the profile file.
- When the wrapper starts, it creates a clean `~/.unison` folder for both local and remote (if exists). Existing folders are renamed before for backup purposes. They will NOT be restored after the wrapper, because restoring them would make the program complicated, would encourage existing behaviour, and would bring complexity in maintenance.
- When the wrapper starts, it populates `~/.unison` with the required profile file and archive files. When it ends, it moves those files back to the folder and remove the temporary `~/.unison`.
- The local archives are stored in the `local` sub-folder, remote ones in the `remote` sub-folder. 

The wrapper checks and records the following information:
- the localhost name, and use `UNISONLOCALHOSTNAME` if available.
- the remote hostname, and its `UNISONLOCALHOSTNAME` if available.

# TODO

- Check validity of path_spec for root.
- Deal with Windows path (local)
- Deal with Windows remote.

# Appendix

**Archive files (from Unison doc)**

```text
The name of the archive file on each replica is calculated from
 * the canonical names of all the hosts (short names like saul are
   converted into full addresses like saul.cis.upenn.edu),
 * the paths to the replicas on all the hosts (again, relative
   pathnames, symbolic links, etc. are converted into full, absolute
   paths), and
 * an internal version number that is changed whenever a new Unison
   release changes the format of the information stored in the
   archive.

This method should work well for most users. However, it is
occasionally useful to change the way archive names are generated.
Unison provides two ways of doing this.

The function that finds the canonical hostname of the local host (which
is used, for example, in calculating the name of the archive file used
to remember which files have been synchronized) normally uses the
gethostname operating system call. However, if the environment variable
UNISONLOCALHOSTNAME is set, its value will be used instead. This makes
it easier to use Unison in situations where a machine’s name changes
frequently (e.g., because it is a laptop and gets moved around a lot).

A more powerful way of changing archive names is provided by the
rootalias preference. The preference file may contain any number of
lines of the form:
rootalias = //hostnameA//path-to-replicaA -> //hostnameB/path-to-replicaB

When calculating the name of the archive files for a given pair of
roots, Unison replaces any root that matches the left-hand side of any
rootalias rule by the corresponding right-hand side.

So, if you need to relocate a root on one of the hosts, you can add a
rule of the form:
rootalias = //new-hostname//new-path -> //old-hostname/old-path

Note that root aliases are case-sensitive, even on case-insensitive
file systems.
```

**Install this package locally**

Install: `pipx install ./`. Upgrade: `pipx upgrade unison-wrapper`.