# ota.py
# micropython OTA update from github
#
# Pulls files and folders from open github repository

import binascii
import hashlib
import json
import logging
import os
import re
import time

# import machine
# import network
try:
    import urequests
except ImportError:
    # In case we are debugging, try to import regular requests lib
    import requests as urequests

global internal_tree

# -------------User Variables---------------- #
try:
    import secrets

    ssid = secrets.ssid
    password = secrets.password
    user = secrets.user
    repository = secrets.repository
    token = secrets.token
except ImportError as e:
    # Default Network to connect
    ssid = "test"
    password = "12345678"

    # CHANGE TO YOUR REPOSITORY INFO
    # Repository must be public if no personal access token is supplied
    user = 'ishamrai'
    repository = 'ota_test'
    token = ''

# Don't remove ota.py from the ignore_files unless you know what you are doing :D
# Put the files you don't want deleted or updated here use '/filename.ext'
# ignore_files = ['/ota.py', '/secrets.py']
ignore_files = ['./ota.py', './secrets.py', r'.idea/.*', 'README.md', 'LICENSE', '.gitignore']
ignore = ignore_files
# -----------END OF USER VARIABLES ---------- #


class GitTreeElement:
    def __init__(self, path, mode, type, sha, url, size=0):
        self.path = os.path.normpath(path)
        self.mode = mode
        self.type = type
        self.sha = sha
        self.size = size
        self.url = url


class GitTree:
    def __init__(self, sha, url, tree, truncated):
        self.sha = sha
        self.url = url
        self.tree = [GitTreeElement(**tree_item) for tree_item in tree]
        self.truncated = truncated

    @classmethod
    def from_response(cls, response):
        return cls.from_json(json.loads(response.content.decode('utf-8')))

    @classmethod
    def from_json(cls, json_data):
        return cls(**json_data)


class WlanManager:
    def __init__(self, wlan_ssid=ssid, wlan_password=password):
        self.ssid = wlan_ssid
        self.password = wlan_password
        # self.wlan = network.WLAN(network.STA_IF)
        self.wlan.active(False)
        self.wlan.active(True)
        self.wlan.connect(self.ssid, self.password)
        while not self.wlan.isconnected():
            pass
        self.is_connected = self.wlan.isconnected
        self.ifconfig = self.wlan.ifconfig()


class GitManager:
    headers = {'User-Agent': 'ota-esp32'}

    def __init__(self, username=user, repo_name=repository, token=token):
        self.username = username
        self.repo_name = repo_name
        self.token = token
        if self.token != '':
            self.headers['authorization'] = "bearer %s" % token
        self.url = f'https://github.com/{self.username}/{self.repo_name}'
        self.tree_url = f'https://api.github.com/repos/{self.username}/{self.repo_name}/git/trees/main?recursive=1'
        self.raw = f'https://raw.githubusercontent.com/{self.username}/{self.repo_name}/master/'

        self.tree = self._get_tree()

    def pull_file(self, destination_file_path, file_path):
        logging.info(f"Pulling {destination_file_path} from github")
        with open(destination_file_path, 'w') as destination_file:
            destination_file.write(self._get_file_content(file_path))

    def _get_file_content(self, file_path):
        logging.info(f"Getting content of {file_path}")
        return urequests.get(f"{self.raw}/{file_path}", headers=self.headers).content.decode('utf-8')

    def _get_tree(self):
        response = urequests.get(self.tree_url, headers=self.headers)
        return GitTree.from_response(response)


class OTA:
    def __init__(self, wlan_ssid=ssid, wlan_password=password,
                 git_username=user, git_repo=repository, ignore_list=None,
                 update_url='https://raw.githubusercontent.com/ishamrai/esp32-ota/master/ota.py'):
        self.update_url = update_url
        if ignore_list is None:
            ignore_list = [os.path.normpath(_file) for _file in ignore_files]
        self.ignore_list = ignore_list
        # self.wlan = WlanManager(wlan_ssid=wlan_ssid, wlan_password=wlan_password)
        self.git = GitManager(username=git_username, repo_name=git_repo)
        self.internal_tree = self.build_internal_tree()

    def _list_dir(self, path):
        result = []
        for sub_path in os.listdir(path):
            _path = os.path.normpath(os.path.join(path, sub_path))
            if os.path.isfile(_path):
                result.append(_path)
            elif os.path.isdir(_path):
                files = self._list_dir(_path)
                result.extend(files)
        return result

    def _get_sha(self, file_path):
        with open(file_path) as rfile:
            return binascii.hexlify(hashlib.sha1(rfile.read().encode("utf-8")).digest())

    def _filter_ignore_items(self, tree):
        _tree = []
        for item in tree:
            if any(re.match(_ignore, item[0]) for _ignore in self.ignore_list):
                logging.warning(f"Skip {item[0]} based on ignore list")
                continue
            _tree.append(item)
        return _tree

    def build_internal_tree(self):
        tree = self._build_internal_tree()
        return self._filter_ignore_items(tree)

    def _build_internal_tree(self):
        return [(_file, self._get_sha(_file)) for _file in self._list_dir('./')]

    def self_update(self):
        logging.info('Updating ota.py to newest version')
        self.git.pull_file('ota.py', self.update_url)

    def pull_repo(self):
        for item in self.git.tree.tree:
            if any(re.match(_ignore, item.path) for _ignore in self.ignore_list):
                logging.warning(f"Skip {item.path} based on ignore list")

            if item.type == 'blob':  # file
                if os.path.exists(item.path):
                    logging.info(f"Deleting {item.path} file.")
                    os.remove(item.path)
                self.git.pull_file(item.path, item.path)
            elif item.type == 'tree' and not os.path.exists(item.path):  # folder
                logging.info(f"Creating {item.path} directory.")
                os.mkdir(item.path)
            else:
                logging.error(f"Unexpected git tree item[{item.type}]: {item}")

    def backup_all(self):
        full_tree = self._build_internal_tree()
        with open('ota.backup') as backup:
            for item in full_tree:
                with open(item[0], 'r') as target:
                    backup.write(f'FN:SHA1{item[0]},{item[1]}\n')
                    backup.write('---' + target.read() + '---\n')
