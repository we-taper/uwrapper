#! python3
import re
import shutil
import sys
import typing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from subprocess import check_output

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
    print(_color_msg(f'[{WRAPPER_NAME} ERROR] {msg}', bcolors.FAIL_RED), file=sys.stderr)


def info(msg):
    print(_color_msg(f'[{WRAPPER_NAME}] {msg}', bcolors.OK_GREEN))


def warn(msg):
    print(_color_msg(f'[{WRAPPER_NAME} WARN] {msg}', bcolors.WARN_YELLOW))


# %% ------------------------------------------------------------------------
# %% Class and utilities
#
# We store the temporary backup of ~/.unison here:
UNISON_BACKUP_NAME = f'.unison_before_{WRAPPER_NAME}'
LOCAL_ARC_NAME = 'archives_local'
REMOTE_ARC_NAME = 'archives_remote'


@dataclass
class Root:
    path: Path
    is_local: bool
    remote_name: typing.Optional[str] = None


class RemoteSSH:
    def __init__(self, remote_name):
        self.remote_name = remote_name
        self.remote_home = self.execute('echo $HOME').strip()

    def execute(self, cmd: str):
        """Note: this command surround cmd with single quotes.

        If an error happens, the remote error message is shown in stderr, and check_output
        throws a CalledProcessError but without the remote error message.
        """
        return check_output(
            f"ssh {self.remote_name} -T '{cmd}'", shell=True).decode('utf-8')

    def expanduser(self, path: str):
        """Similar to Path(path).expanduser()."""
        if path.startswith('~'):
            path = self.remote_home + path[1:]
        return path

    def path_exists(self, path: str) -> bool:
        path = self.expanduser(path)
        ret = self.execute(f'test -e "{path}" && echo "yes" || echo "no"')
        ret = ret.strip()
        if ret == "yes":
            return True
        elif ret == "no":
            return False
        else:
            raise RuntimeError(f'Unexpected output from ssh: {ret}')

    def mkdir(self, path: str):
        path = self.expanduser(path)
        return self.execute(f'mkdir -p "{path}"')

    def move(self, old_path: str, new_path: str):
        old_path = self.expanduser(old_path)
        new_path = self.expanduser(new_path)
        return self.execute(f'mv "{old_path}" "{new_path}"')

    def dir_local2remote(self, local_path: typing.Union[str, Path], remote_path: str):
        # Note:
        # - we don't use rsync, since rsync requires a remote installation as well.
        # -  we add "-O" option to scp, so that we are compatible when the remote ssh does
        #    not have implement SFTP protocol.
        if isinstance(local_path, Path):
            local_path = str(local_path.absolute()) + '/'
        remote_path = self.expanduser(remote_path)
        if not local_path.endswith('/') or not remote_path.endswith('/'):
            raise ValueError(f'Both local_path and remote_path should end with "/"')
        return check_output(
            f'scp -O -r "{local_path}" "{self.remote_name}:{remote_path}"',
            shell=True
        ).decode('utf-8')

    def dir_remote2local(self, remote_path: str, local_path: typing.Union[str, Path]):
        if isinstance(local_path, Path):
            local_path = str(local_path.absolute()) + '/'
        remote_path = self.expanduser(remote_path)
        if not local_path.endswith('/') or not remote_path.endswith('/'):
            raise ValueError(f'Both local_path and remote_path should end with "/"')
        return check_output(
            f'scp -O -r "{self.remote_name}:{remote_path}" "{local_path}"',
            shell=True
        ).decode('utf-8')


@dataclass
class Profile:
    file: Path
    folder: Path
    roots: typing.Tuple[Root, Root]
    contain_remote: bool
    remote_name: typing.Optional[str]
    remote_root: typing.Optional[Root]
    remote_ssh: typing.Optional[RemoteSSH]


# %% ------------------------------------------------------------------------
# %% Main programs
#
def read_profile(profile_file) -> Profile:
    if not profile_file.endswith('.prf'):
        raise RuntimeError(f'Profile file must ends with the extension .prf: {profile_file}')
    file = Path(profile_file)
    content = file.read_text(encoding='utf-8')
    root_pattern = re.compile(r'^root\s*=\s*(.+)$')
    assert not root_pattern.match('root=')
    assert root_pattern.match('root=asdf').groups() == ('asdf',)
    assert root_pattern.match('root  =  asdf').groups() == ('asdf',)

    roots = []
    for line in content.split('\n'):
        m = root_pattern.match(line)
        if m:
            root_spec = m.groups()[0]
            if root_spec.startswith('ssh://'):
                is_local = False
                root_spec = root_spec[6:]
                remote_name = root_spec[:root_spec.find('/')]
                path = root_spec[root_spec.find('/') + 1:]
                roots.append(Root(path, is_local, remote_name))
            else:
                path = root_spec
                roots.append(Root(path, True, None))
    if len(roots) != 2:
        raise RuntimeError(f'Found root paths invalid: {roots}')

    root_a, root_b = roots

    if not root_a.is_local and not root_b.is_local:
        raise RuntimeError('At least one of the root should be local.')
    contain_remote = not all((root_a.is_local, root_b.is_local))
    if contain_remote:
        remote_root = root_a if not root_a.is_local else root_b
        remote_name = remote_root.remote_name
        assert remote_name is not None
        remote_shell = RemoteSSH(remote_name)
    else:
        remote_root = None
        remote_name = None
        remote_shell = None

    return Profile(
        file=file, folder=file.parent,
        roots=(root_a, root_b), contain_remote=contain_remote,
        remote_name=remote_name,
        remote_root=remote_root, remote_ssh=remote_shell
    )


def start(profile: Profile):
    # check for local .unison
    u_folder = Path('~/.unison').expanduser()
    if u_folder.exists():
        u_backup_folder = Path(f'~/{UNISON_BACKUP_NAME}').expanduser()
        if u_backup_folder.exists():
            error(f'Found existing backup folder {u_backup_folder} while ~/.unison exists!'
                  '\nCheck why! Quit.')
            return -1
        shutil.move(u_folder, u_backup_folder)
        info(f'Existing ~/.unison is moved to ~/{UNISON_BACKUP_NAME}')

    # check for remote .unison
    if profile.contain_remote:
        if profile.remote_ssh.path_exists('~/.unison'):
            if profile.remote_ssh.path_exists(f'~/{UNISON_BACKUP_NAME}'):
                error(f"On {profile.remote_name}, found existing remote backup "
                      f"folder ~/{UNISON_BACKUP_NAME} while ~/.unison exists!"
                      " Check why! Quit.")
                return -1
            profile.remote_ssh.move('~/.unison', f'~/{UNISON_BACKUP_NAME}')
            if profile.remote_ssh.path_exists(f'~/{UNISON_BACKUP_NAME}') and \
                    not profile.remote_ssh.path_exists(f'~/.unison'):
                info(f'Existing ~/.unison on {profile.remote_name} is moved to ~/{UNISON_BACKUP_NAME}')
            else:
                error(f"Failed to move existing ~/.unison to ~/{UNISON_BACKUP_NAME}. "
                      "Check why! Quit.")
                return -1

    # now that the .unison cleaned, start populating it.
    today = datetime.today().strftime('%Y%m%d')
    backup_f = profile.folder / 'archives_backup' / today
    local_archive_f = profile.folder / LOCAL_ARC_NAME
    if local_archive_f.exists():
        # move all files under local to .unison
        info('Copying all archive files to ~/.unison')
        shutil.copytree(local_archive_f, u_folder)
        backup_f.mkdir(parents=True, exist_ok=True)
        shutil.move(local_archive_f, backup_f / LOCAL_ARC_NAME)
    else:
        info(f'No local archive files found.')
        u_folder.mkdir()  # creates empty ~/.unison

    if profile.contain_remote:
        remote_archive_f = profile.folder / REMOTE_ARC_NAME
        if remote_archive_f.exists():
            # move all files under remote to .unison
            info(f'Copying all remote archive files to ~/.unison on {profile.remote_name}')
            profile.remote_ssh.dir_local2remote(remote_archive_f, '~/.unison/')
            backup_f.mkdir(parents=True, exist_ok=True)
            shutil.move(remote_archive_f, backup_f / REMOTE_ARC_NAME)
        else:
            info(f'No remote archive files found.')
            profile.remote_ssh.mkdir('~/.unison/')

    info("Copying profile to ~/.unison")
    shutil.copy(profile.file, u_folder / profile.file.name)
    info(f"Now ready to run: unison {profile.file.name}")


def restore(profile: Profile):
    u_folder = Path('~/.unison').expanduser()
    assert u_folder.exists() and u_folder.is_dir()
    profile_file_in_u = u_folder / profile.file.name
    if not profile_file_in_u.exists():
        error(f'Profile file {profile.file.name} not found in ~/.unison. Check why! Quit.')
        return -1

    # first copy back archives
    profile_file_in_u.unlink()  # this file is a copy, no need to keep.
    info(f'Moving local archives back to {profile.folder}/{LOCAL_ARC_NAME}.')
    # everything under ~/.unison are archives now.
    shutil.copytree(u_folder, profile.folder / LOCAL_ARC_NAME)

    if profile.contain_remote:
        info(f"Moving remote archives back to {profile.folder}/{REMOTE_ARC_NAME}.")
        profile.remote_ssh.dir_remote2local("~/.unison/", profile.folder / REMOTE_ARC_NAME)

    # then destroy now-useless copies in ~/.unison
    info("Deleting ~/.unison")
    shutil.rmtree(u_folder)
    if profile.contain_remote:
        info(f"Deleting ~/.unison on {profile.remote_name}")
        profile.remote_ssh.execute(f'rm -rf ~/.unison/')
        if profile.remote_ssh.path_exists('~/.unison'):
            warn(f"Failed to delete ~/.unison on {profile.remote_name}. Please remove it manually!")

    # then restores old .unison if exists
    # u_backup_folder = Path(f'~/{UNISON_BACKUP_NAME}').expanduser()
    # if u_backup_folder.exists():
    #     info(f"Restoring ~/.unison from ~/{u_backup_folder}")
    #     shutil.move(u_backup_folder, u_folder)
    # if profile.contain_remote:
    #     r_backup = '~/' + UNISON_BACKUP_NAME
    #     if profile.remote_ssh.path_exists(r_backup):
    #         info(f"Restoring ~/.unison from {r_backup} on {profile.remote_name}")
    #         profile.remote_ssh.move(r_backup, '~/.unison/')


def main():
    if len(sys.argv) != 3:
        error(f'Usage: {sys.argv[0]} [start or s|restore or r] <profile_file>')
        return -1
    option = sys.argv[1]
    profile_file = sys.argv[2]
    try:
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


if __name__ == '__main__':
    sys.exit(main())
