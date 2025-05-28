from subprocess import check_output
from pathlib import Path, PureWindowsPath


class RemoteSSHWindows:
    def __init__(self, remote_name):
        self.remote_name = remote_name
        self.remote_home = self.find_home()

    def execute(self, cmd: str):
        """Note: this command surround cmd with single quotes.

        If an error happens, the remote error message is shown in stderr, and check_output
        throws a CalledProcessError but without the remote error message.
        """
        return check_output(
            f"ssh {self.remote_name} -T '{cmd}'", shell=True).decode('utf-8')

    def check_powershell(self):
        output = self.execute("echo $PSVersionTable")
        return 'PSEdition' in output

    def find_home(self):
        output = self.execute("echo $env:USERPROFILE")
        output = output.strip()  # strip newline characters
        return PureWindowsPath(output)

    def path_exists(self, path: PureWindowsPath):
        cmd = f"Test-Path -Path \"{path}\""
        output = self.execute(cmd).strip()
        if output == 'True':
            return True
        elif output == 'False':
            return False
        else:
            raise ValueError(output)

    def unison_exists(self):
        path = self.remote_home / '.unison'
        return self.path_exists(path)

    def unison_backup_exists(self):
        path = self.remote_home / '.unison_before_uwrapper'
        return self.path_exists(path)

    def create_remote_unison_dir(self):
        path = self.remote_home / '.unison'
        return self.execute(f'New-Item -Path "{path}" -ItemType Directory')

    def remove_remote_unison_dir(self):
        path = self.remote_home / '.unison'
        # -Recurse for folders
        return self.execute(f'Remove-Item -Path "{path}" -Recurse')

    def move_remote_unison_to_backup(self):
        old_unison = self.remote_home / '.unison'
        new_unison = self.remote_home / '.unison_before_uwrapper'
        return self.execute(f'Rename-Item -Path "{old_unison}" -NewName "{new_unison}"')

    def copy_local_archive_to_remote_unison(self):
        # local_archive_dir = Path("/Users/hchen/code/taper-misc/uwrapper/src")
        remote_path = self.remote_home / ".unison"
        return check_output(
            f'scp -r "{local_archive_dir}" "{self.remote_name}:{remote_path}"',
            shell=True
        ).decode('utf-8')

    def copy_remote_unison_to_local(self):
        # local_archive_dir = Path("/Users/hchen/code/taper-misc/uwrapper/src/delme")
        remote_path = self.remote_home / ".unison"
        # test shows that \ -> / substitution is necessary, otherwise scp reports "No such file or directory"
        remote_path = str(remote_path).replace('\\', '/')
        return check_output(
            f'scp -r "{self.remote_name}:{remote_path}" "{local_archive_dir}"',
            shell=True
        ).decode('utf-8')


def main():
    ssh = RemoteSSH('uwin')
    print(ssh.copy_remote_unison_to_local())


if __name__ == '__main__':
    main()
