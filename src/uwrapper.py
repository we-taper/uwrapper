#! python3
"""A wrapper around unison.
Organised into: Basic logging, Remote utilities, Main programs
"""
import re
import shutil
import sys
import typing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from subprocess import check_output
from urllib.parse import urlparse

WRAPPER_NAME = 'uwrapper'


# %% ------------------------------------------------------------------------
# %% Basic logging
#
class bcolors:
    # https://stackoverflow.com/questions/287871/how-do-i-print-colored-text-to-the-terminal
    # Also, colors guessed from https://gist.github.com/nazwadi/ca00352cd0d20b640efd
    HEADER_PURPLE = '\033[95m'
    OK_BLUE = '\033[94m'
    OK_CYAN = '\033[96m'
    OK_DARKCYAN = '\033[36m'
    OK_GREEN = '\033[92m'
    WARN_YELLOW = '\033[93m'
    FAIL_RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def _color_msg(msg, color):
    return f'{color}{msg}{bcolors.ENDC}'


def error(msg):
    print(
        _color_msg(f'[{WRAPPER_NAME} ERROR] {msg}', bcolors.FAIL_RED),
        file=sys.stderr
    )


def info(msg):
    print(_color_msg(f'[{WRAPPER_NAME}] {msg}', bcolors.OK_GREEN))


def warn(msg):
    print(_color_msg(f'[{WRAPPER_NAME} WARN] {msg}', bcolors.WARN_YELLOW))


# %% ------------------------------------------------------------------------
# %% Remote utilities


class RemoteSSH:
    def __init__(self, remote_name: str):
        self.remote_name = remote_name

    @property
    def remote_unison(self) -> str:
        raise NotImplementedError(type(self))

    @property
    def remote_backup(self) -> str:
        raise NotImplementedError(type(self))

    def unison_exists(self) -> bool:
        raise NotImplementedError(type(self))

    def unison_backup_exists(self) -> bool:
        raise NotImplementedError(type(self))

    def move_remote_unison_to_backup(self):
        raise NotImplementedError(type(self))

    def move_remote_backup_to_unison(self):
        raise NotImplementedError(type(self))

    def create_remote_unison_dir(self):
        raise NotImplementedError(type(self))

    def copy_archive_folder_to_remote_unison(self, archive_folder: Path):
        raise NotImplementedError(type(self))

    def copy_remote_archives_back(self, archive_folder: Path):
        raise NotImplementedError(type(self))

    def delete_remote_unison(self):
        raise NotImplementedError(type(self))


class RemoteSSHUnix(RemoteSSH):
    def __init__(self, remote_name):
        super().__init__(remote_name)
        self.remote_home = PurePosixPath(self.execute('echo $HOME').strip())
        self._remote_unison = self.remote_home / '.unison'
        self._remote_backup = self.remote_home / UNISON_BACKUP_NAME

    @property
    def remote_unison(self):
        return str(self._remote_unison)

    @property
    def remote_backup(self):
        return str(self._remote_backup)

    def execute(self, cmd: str):
        """Note: this command surround cmd with single quotes.

        If an error happens, the remote error message is shown in stderr, and check_output
        throws a CalledProcessError but without the remote error message.
        """
        return check_output(f"ssh {self.remote_name} -T '{cmd}'",
                            shell=True).decode('utf-8')

    def _path_exists(self, path: PurePosixPath) -> bool:
        ret = self.execute(f'test -e "{path}" && echo "yes" || echo "no"')
        ret = ret.strip()
        if ret == "yes":
            return True
        elif ret == "no":
            return False
        else:
            raise RuntimeError(
                f'When testing path existence, got unexpected output from ssh: {ret}'
            )

    def _mkdir(self, path: PurePosixPath):
        self.execute(f'mkdir -p "{path}"')
        if not self._path_exists(path):
            raise RuntimeError(
                f'Failed to create "{path}" on remote "{self.remote_name}"'
            )

    def _move(self, old_path: PurePosixPath, new_path: PurePosixPath):
        self.execute(f'mv "{old_path}" "{new_path}"')
        if not self._path_exists(old_path) and self._path_exists(new_path):
            return
        else:
            raise RuntimeError(
                f'Failed to move "{old_path}" to "{new_path}" on remote "{self.remote_name}"'
            )

    def _dir_local2remote(
            self, local_path: Path, remote_path: PurePosixPath
    ):
        # Note:
        # - we don't use rsync, since rsync requires a remote installation as well.
        # -  we add "-O" option to scp, so that we are compatible when the remote ssh does
        #    not have implement SFTP protocol.
        check_output(
            f'scp -O -r "{local_path}" "{self.remote_name}:{remote_path}"',
            shell=True
        )
        if not self._path_exists(remote_path):
            raise RuntimeError(
                f'Failed to copy "{local_path}" to "{remote_path}" in remote "{self.remote_name}".'
            )

    def _dir_remote2local(
            self, remote_path: PurePosixPath, local_path: Path
    ):
        check_output(
            f'scp -O -r "{self.remote_name}:{remote_path}" "{local_path}"',
            shell=True
        )

    def unison_exists(self):
        return self._path_exists(self._remote_unison)

    def unison_backup_exists(self):
        return self._path_exists(self._remote_backup)

    def move_remote_unison_to_backup(self):
        self._move(self._remote_unison, self._remote_backup)

    def move_remote_backup_to_unison(self):
        self._move(self._remote_backup, self._remote_unison)

    def create_remote_unison_dir(self):
        self._mkdir(self._remote_unison)

    def copy_archive_folder_to_remote_unison(self, archive_folder: Path):
        self._dir_local2remote(archive_folder, self._remote_unison)

    def copy_remote_archives_back(self, archive_folder: Path):
        self._dir_remote2local(self._remote_unison, archive_folder)
        if archive_folder.exists() and archive_folder.is_dir(
        ) and any(archive_folder.iterdir()):
            return
        else:
            raise RuntimeError(
                f'Failed to copy back archives inside remote\'s "~/.unison".'
                f' Check local folder {archive_folder} and the remote "{self.remote_name}".'
            )

    def delete_remote_unison(self):
        self.execute(f'rm -rf {self.remote_unison}')
        if self._path_exists(self._remote_unison):
            raise RuntimeError(f'Failed to remove "{self.remote_unison}" on remote "{self.remote_name}"')


class RemoteSSHWindows(RemoteSSH):
    def __init__(self, remote_name):
        super().__init__(remote_name)
        self._remote_home = self._find_home()
        self._remote_unison = self._remote_home / '.unison'
        self._remote_backup = self._remote_home / UNISON_BACKUP_NAME

    @property
    def remote_unison(self):
        return str(self._remote_unison)

    @property
    def remote_backup(self):
        return str(self._remote_backup)

    def execute(self, cmd: str):
        """Note: this command surround cmd with single quotes.

        If an error happens, the remote error message is shown in stderr, and check_output
        throws a CalledProcessError but without the remote error message.
        """
        return check_output(
            f"ssh {self.remote_name} -T '{cmd}'", shell=True).decode('utf-8')

    def support_powershell(self):
        output = self.execute("echo $PSVersionTable")
        return 'PSEdition' in output

    def _find_home(self):
        output = self.execute("echo $env:USERPROFILE")
        output = output.strip()  # strip newline characters
        return PureWindowsPath(output)

    def _path_exists(self, path: PureWindowsPath):
        cmd = f"Test-Path -Path \"{path}\""
        output = self.execute(cmd).strip()
        if output == 'True':
            return True
        elif output == 'False':
            return False
        else:
            raise ValueError(output)

    def _mkdir(self, path: PureWindowsPath):
        self.execute(f'New-Item -Path "{path}" -ItemType Directory')
        if not self._path_exists(path):
            raise RuntimeError(f'Failed to create "{path}" on "{self.remote_name}"')

    def _move(self, old: PureWindowsPath, new: PureWindowsPath):
        self.execute(f'Rename-Item -Path "{old}" -NewName "{new}"')
        if self._path_exists(new) and not self._path_exists(old):
            return
        else:
            raise RuntimeError(f'Failed to move "{old}" to "{new}" on "{self.remote_name}"')

    def unison_exists(self):
        return self._path_exists(self._remote_unison)

    def unison_backup_exists(self):
        return self._path_exists(self._remote_backup)

    def move_remote_unison_to_backup(self):
        self._move(self._remote_unison, self._remote_backup)

    def move_remote_backup_to_unison(self):
        self._move(self._remote_backup, self._remote_unison)

    def create_remote_unison_dir(self):
        self._mkdir(self._remote_unison)

    def copy_archive_folder_to_remote_unison(self, archive_folder: Path):
        return check_output(
            f'scp -r "{archive_folder}" "{self.remote_name}:{self._remote_unison}"',
            shell=True
        ).decode('utf-8')

    def copy_remote_archives_back(self, archive_folder: Path):
        # test shows that \ -> / substitution is necessary, otherwise scp reports "No such file or directory"
        remote_path = str(self._remote_unison).replace('\\', '/')
        return check_output(
            f'scp -r "{self.remote_name}:{remote_path}" "{archive_folder}"',
            shell=True
        ).decode('utf-8')

    def delete_remote_unison(self):
        # -Recurse for folders
        self.execute(f'Remove-Item -Path "{self._remote_unison}" -Recurse')
        if self.unison_exists():
            raise RuntimeError(f'Failed to remove "{self._remote_unison}" on "{self.remote_name}"')


# %% ------------------------------------------------------------------------
# %% Main programs
UNISON_BACKUP_NAME = f'.unison_before_{WRAPPER_NAME}'
LOCAL_ARC_NAME = 'archives_local'
REMOTE_ARC_NAME = 'archives_remote'


@dataclass
class Root:
    path: str
    is_local: bool
    remote_name: typing.Optional[str] = None
    remote_type: typing.Optional[typing.Literal['Windows', "Unix"]] = None


@dataclass
class Profile:
    cfg_file: Path
    data_folder: Path
    roots: typing.Tuple[Root, Root]
    contain_remote: bool
    remote_name: typing.Optional[str]
    remote_root: typing.Optional[Root]
    remote_ssh: typing.Optional[RemoteSSH]


def read_profile(profile_file: Path) -> Profile:
    if not profile_file.name.endswith('.prf'):
        raise RuntimeError(
            f'Profile file did not end with the extension .prf: {profile_file}'
        )
    content = profile_file.read_text(encoding='utf-8')
    root_pattern = re.compile(r'^root\s*=\s*(.+)$')
    assert not root_pattern.match('root=')
    assert root_pattern.match('root=asdf').groups() == ('asdf',)
    assert root_pattern.match('root  =  asdf').groups() == ('asdf',)

    def parse_root_path(path: str):
        parsed = urlparse(path)
        if parsed.scheme == '':
            return Root(path, True)
        if parsed.scheme == 'ssh':
            name = parsed.netloc
            if parsed.path.startswith('//'):
                return Root(parsed.path[1:], False, name, 'Unix')
            if parsed.path[0] == '/' and parsed.path[1].isalpha() and parsed.path[2] == ':':
                return Root(parsed.path[1:], False, name, 'Windows')
        raise ValueError(f"Failed to understand this root: {path}")

    assert parse_root_path('/home/xx/') == Root('/home/xx/', True)
    assert parse_root_path('ssh://remote//home/xx/') == Root('/home/xx/', False, 'remote', 'Unix')
    assert parse_root_path('ssh://wr/d:\\Users\\hc\\code\\') == Root('d:\\Users\\hc\\code\\', False, 'wr', 'Windows')

    roots = []
    for line in content.split('\n'):
        m = root_pattern.match(line)
        if m:
            root_spec = m.groups()[0]
            roots.append(parse_root_path(root_spec))
            # if root_spec.startswith('ssh://'):
            #     is_local = False
            #     root_spec = root_spec[6:]
            #     remote_name = root_spec[:root_spec.find('/')]
            #     path = root_spec[root_spec.find('/') + 1:]
            #     roots.append(Root(path, is_local, remote_name))
            # else:
            #     path = root_spec
            #     roots.append(Root(path, True, None))
    if len(roots) != 2:
        raise RuntimeError(f'Invalid root specification. Found these roots: {roots}')

    root_a, root_b = roots

    if not root_a.is_local and not root_b.is_local:
        raise RuntimeError('At least one of the root should be local.')
    contain_remote = not all((root_a.is_local, root_b.is_local))
    if contain_remote:
        remote_root = root_a if not root_a.is_local else root_b  # type: typing.Optional[Root]
        remote_name = remote_root.remote_name
        assert remote_name is not None
        if remote_root.remote_type == 'Unix':
            remote_shell = RemoteSSHUnix(remote_name)
        elif remote_root.remote_type == 'Windows':
            remote_shell = RemoteSSHWindows(remote_name)
        else:
            raise ValueError(f'Invalid value: {remote_root.remote_type=}')
    else:
        remote_root = None
        remote_name = None
        remote_shell = None

    assert profile_file.name.endswith('.prf')
    data_folder = profile_file.parent / profile_file.name[:-4]  # with extension removed
    data_folder.mkdir(exist_ok=True)
    return Profile(
        cfg_file=profile_file,
        data_folder=data_folder,
        roots=(root_a, root_b),
        contain_remote=contain_remote,
        remote_name=remote_name,
        remote_root=remote_root,
        remote_ssh=remote_shell
    )


def start(profile: Profile):
    # Check for local .unison, rename to a backup if exists.
    u_folder = Path('~/.unison').expanduser()
    if u_folder.exists():
        u_backup_folder = Path(f'~/{UNISON_BACKUP_NAME}').expanduser()
        if u_backup_folder.exists():
            error(
                f'Found existing backup folder "{u_backup_folder}" while "{u_folder}" exists!'
                '\nThis is unexpected. Check why! Quit.'
            )
            return -1
        shutil.move(u_folder, u_backup_folder)
        info(f'Existing "{u_folder}" is moved to "{u_backup_folder}"')

    if profile.contain_remote:
        # Check for remote folder status.
        # If both unison and the backup exists: unexpected and quit.
        # If both are missing: good.
        # If only unison folder: move to "backup". If only the backup: good.
        remote_ssh = profile.remote_ssh
        if remote_ssh.unison_exists():
            if remote_ssh.unison_backup_exists():
                error(
                    f'On "{profile.remote_name}", found existing remote backup '
                    f'folder "{remote_ssh.remote_backup}" while "{remote_ssh.remote_unison}" exists!'
                    "\nThis is unexpected. Check why! Quit."
                )
                return -1
            # else (not unison_backup_exists):
            remote_ssh.move_remote_unison_to_backup()
            info(
                f'Existing "{remote_ssh.remote_unison}" on "{profile.remote_name}"'
                f' is moved to "{remote_ssh.remote_backup}"'
            )

    # Main program
    backup_f = profile.data_folder / 'archives_backup' / datetime.today().strftime('%Y%m%d')

    # Copy local archives to .unison
    local_archive_f = profile.data_folder / LOCAL_ARC_NAME
    if not local_archive_f.exists():
        info(f'No local archive files found.')
        u_folder.mkdir()  # creates empty ~/.unison
    else:
        # move all files under local to .unison
        shutil.copytree(local_archive_f, u_folder)
        info(f'Archives in "{local_archive_f}" copied to "{u_folder}"')
        backup_f.mkdir(parents=True, exist_ok=True)
        backup_f_local_archive = backup_f / LOCAL_ARC_NAME
        if backup_f_local_archive.exists():
            shutil.rmtree(backup_f_local_archive)
        shutil.move(local_archive_f, backup_f_local_archive)
        info(f'Archives in "{local_archive_f}" moved to "{backup_f_local_archive}"')

    if profile.contain_remote:
        # Copy target archives to remote's .unison
        remote_archive_f = profile.data_folder / REMOTE_ARC_NAME
        if not remote_archive_f.exists():
            info(f'No remote archive files found.')
            # Note: note need to create an empty remote unison directory here.
        else:
            # move all files under remote to .unison
            remote_ssh = profile.remote_ssh
            remote_ssh.copy_archive_folder_to_remote_unison(remote_archive_f)
            info(f'Remote archive files copied to "{remote_ssh.remote_unison}" on "{profile.remote_name}"')
            backup_f.mkdir(parents=True, exist_ok=True)
            backup_f_remote_archive = backup_f / REMOTE_ARC_NAME
            if backup_f_remote_archive.exists():
                shutil.rmtree(backup_f_remote_archive)
            shutil.move(remote_archive_f, backup_f_remote_archive)
            info(f'Archives in "{remote_archive_f}" moved to "{backup_f_remote_archive}"')

    shutil.copy(profile.cfg_file, u_folder / profile.cfg_file.name)
    info(f'Profile "{profile.cfg_file}" copied to "{u_folder}"')
    info(f"Now ready. Please run: unison {profile.cfg_file.name}")


def restore(profile: Profile):
    u_folder = Path('~/.unison').expanduser()
    if u_folder.exists() and u_folder.is_dir():
        pass
    else:
        error(f'Cannot found "{u_folder}" folder locally.')
        return -1
    profile_file_in_u = u_folder / profile.cfg_file.name
    if not profile_file_in_u.exists():
        error(
            f'Profile file "{profile.cfg_file.name}" not found in "{u_folder}". Check why! Quit.'
        )
        return -1

    # First, copy back local archives
    profile_file_in_u.unlink()  # Clear local unison cfg file, as it is a copy and clutters the unison directory.
    # everything under ~/.unison are archives now.
    local_archive = profile.data_folder / LOCAL_ARC_NAME
    shutil.move(u_folder, local_archive)
    info(f'Moved local archives back to "{local_archive}".')
    u_backup_folder = Path(f'~/{UNISON_BACKUP_NAME}').expanduser()
    if u_backup_folder.exists():
        shutil.move(u_backup_folder, u_folder)
        info(f'Restored local backup "{u_backup_folder}" to "{u_folder}"')

    if profile.contain_remote:
        # Then, copy back remote archives
        remote_ssh = profile.remote_ssh
        remote_archive = profile.data_folder / REMOTE_ARC_NAME
        profile.remote_ssh.copy_remote_archives_back(remote_archive)
        info(f'Moved remote archives back to "{remote_archive}".')
        if remote_ssh.unison_backup_exists():
            # Note: we move existing .unison folder before restoring backup, since
            # on certain OS (Window!), existing .unison folder would prevent
            # the move command next line.
            remote_ssh.delete_remote_unison()
            remote_ssh.move_remote_backup_to_unison()
            info(
                f'Restored "{remote_ssh.remote_backup}" to "{remote_ssh.remote_unison}"'
                f' on the remote "{remote_ssh.remote_name}"')
        else:
            remote_ssh.delete_remote_unison()
            info(f'Deleted "{remote_ssh.remote_unison}" on "{profile.remote_name}"')


def main():
    if len(sys.argv) != 3:
        error(f'Usage: {sys.argv[0]} [start or s|restore or r] <profile_file>')
        return -1
    option = sys.argv[1]
    profile_file = sys.argv[2]
    profile_file = Path(profile_file).absolute()
    try:
        info(f'Reading file: {profile_file}')
        profile = read_profile(profile_file)
        info(f'Found Root: {profile.roots[0]}')
        info(f'Found Root: {profile.roots[1]}')
    except RuntimeError as e:
        error(f"Invalid profile file: {profile_file}. Error: {e}")
        return -1

    if option == 'start' or option == 's':
        return start(profile)
    if option == 'restore' or option == 'r':
        return restore(profile)
    error(f'Invalid option: {option}')
    return -1


if __name__ == '__main__':
    sys.exit(main())
