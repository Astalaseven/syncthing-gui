#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import division
import logging
import os
import sys
import time

import arrow
import psutil
from python_qt_binding import QtGui, QtCore
from python_qt_binding.QtGui import *

from syncthing import SyncthingClient

# pip install arrow requests python_qt_binding PySide psutil

logging.basicConfig(filename='syncthing.log',
                    level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

log = logging.getLogger(__name__)

requests_log = logging.getLogger('requests')
requests_log.setLevel(logging.WARNING)

class StatusThread(QtCore.QThread):
    '''
    Thread used to update the status of SyncThing
    '''
    infoRepoMessage = QtCore.Signal(object)
    statusMessage = QtCore.Signal(object)
    nodesMessage = QtCore.Signal(object)

    def run(self):
        log.info('Status thread launched')

        while True:
            if not syncthing_repositories:
                continue

            repos = [repo['ID'] for repo in syncthing_repositories]
            info_repos = self.get_repos_status(repos)
            self.infoRepoMessage.emit(info_repos)

            status = self.get_global_status(info_repos)
            self.statusMessage.emit(status)

            nodes = self.get_connected_nodes()
            self.nodesMessage.emit(nodes)

            time.sleep(5)

    def get_global_status(self, repos):
        status = 0

        for repo in repos:
            status += repo['diff']

        status = status / len(repos)
        status = 'OK' if (status == 100) else 'syncing... (%s%%)' % status

        return status

    def get_connected_nodes(self):
        return syncthing.get_connections()

    def get_repos_status(self, repos):
        info_repos = []

        for repo in repos:
            repo_info = syncthing.get_repo(repo)
            if not repo_info:
                info_repo = {'name': repo, 'diff': -1}
                info_repos.append(info_repo)
                continue

            globalBytes = repo_info['globalBytes']
            localBytes = repo_info['localBytes']

            if globalBytes != 0:
                diff = (localBytes / globalBytes) * 100
            else:
                diff = 100

            diff = int(round(diff))

            info_repo = {'name': repo, 'diff': diff}
            info_repos.append(info_repo)

        return info_repos

class UpdateThread(QtCore.QThread):
    '''
    Thread used to check if Syncthing needs to be updated
    '''
    updateMessage = QtCore.Signal(object)

    def run(self):
        update = self.update_syncthing()
        self.updateMessage.emit(update)

    def update_syncthing(self):
        version = syncthing.get_upgrade()
        if not version:
            return False

        if version['newer']:
            log.info('New version available: %s (actually %s)' % (version['latest'], version['running']))
        else:
            log.info('Syncthing is up to date')

        return version['newer']

class RecentsThread(QtCore.QThread):
    '''
    Thread used to update recently updated files
    '''
    recentsMessage = QtCore.Signal(object)

    def run(self):

        while True:
            events = syncthing.get_events()
            self.recentsMessage.emit(events)

            time.sleep(10)

class SystemTrayIcon(QtGui.QSystemTrayIcon):

    def __init__(self, icon, parent=None):
        QtGui.QSystemTrayIcon.__init__(self, icon, parent)

        ''' Threads '''
        # Status
        self.status_thread = StatusThread()
        self.status_thread.infoRepoMessage.connect(self.handleReposMessage)
        self.status_thread.statusMessage.connect(self.handleStatusMessage)
        self.status_thread.nodesMessage.connect(self.handleNodesMessage)
        self.status_thread.start()

        # Update
        self.update_thread = UpdateThread()
        self.update_thread.updateMessage.connect(self.handleUpdateMessage)

        # Recents
        self.recents_thread = RecentsThread()
        self.recents_thread.recentsMessage.connect(self.handleRecentsMessage)
        self.recents_thread.start()

        self.menu = QtGui.QMenu(parent)

        ''' Status '''
        self.status = QAction('Status: unknown', self.menu)
        self.status.setStatusTip('Test')
        self.status.setToolTip('Test0')
        self.status.triggered.connect(self.open_syncthing_web)
        self.menu.addAction(self.status)

        ''' Folders '''
        self.folders = self.menu.addMenu('Folders')
        self.folders.setIcon(QIcon('icons/folder.png'))
        folders = []
        if syncthing_repositories:
            folders = {repo['ID']: repo['Directory'] for repo in syncthing_repositories}

        for folder in folders:
            item = QAction(folder, self.folders)
            item.triggered.connect(lambda: self.open_dir(folders[folder]))
            item.setIcon(QIcon('icons/sync.png'))
            self.folders.addAction(item)

        ''' Nodes list '''
        self.nodes = self.menu.addMenu('Nodes')
        self.nodes.setIcon(QIcon('icons/node.png'))
        nodes = []
        if syncthing_nodes:
            nodes = {node['NodeID']: node['Name'] for node in syncthing_nodes}

        for node in nodes:
            if node != syncthing.get_self_id():
                item = QAction(nodes[node], self.nodes)
                item.setDisabled(True)
                item.setIcon(QtGui.QIcon('icons/active.png'))
                self.nodes.addAction(item)

        ''' Recents '''
        self.recents = self.menu.addMenu('Recents')
        self.recents.setIcon(QIcon('icons/recent.png'))
        nothing_yet = QAction('(nothing yet)', self.recents)
        nothing_yet.setDisabled(True)
        self.recents.addAction(nothing_yet)
        self.recents.activated.connect(lambda: self.open_dir(folders[folder]))

        ''' Separator '''
        self.menu.addSeparator()

        ''' Update '''
        self.update = QAction('Update', self.menu)
        self.update.triggered.connect(self.update_thread.start)
        self.menu.addAction(self.update)

        ''' Changelog '''
        self.changelog = QAction('View changelog', self.menu)
        self.changelog.triggered.connect(self.view_changelog)
        self.changelog.setVisible(False)
        self.menu.addAction(self.changelog)

        ''' Restart '''
        self.restart = QAction('Restart', self.menu)
        self.restart.triggered.connect(self.restart_syncthing)
        self.menu.addAction(self.restart)

        ''' Separator '''
        self.menu.addSeparator()

        ''' Exit button '''
        self.exitAction = QAction('&Exit', self.menu)
        self.exitAction.triggered.connect(self.quit)
        self.menu.addAction(self.exitAction)

        self.setContextMenu(self.menu)

    def quit(self):
        for proc in psutil.process_iter():
            try:
                if proc.name() in ('syncthing', 'syncthing.exe'):
                    proc.terminate()
            except psutil.AccessDenied:
                continue
        QtGui.qApp.quit()

    def open_syncthing_web(self):
        QDesktopServices.openUrl('http://localhost:8080')

    def restart_syncthing(self):
        if syncthing.syncthing_apikey:
            log.info('Restarting Syncthing...')
            syncthing.restart()
        else:
            msgBox = QDialog()
            msgBox = QMessageBox().information(self, 'No API key', 'Restart needs API key to be configured.' \
            '\n\nGo to \'Edit\', \'Config\' and generate an API key.')
            self.open_syncthing_web()

    def open_dir(self, folder):
        QDesktopServices.openUrl('file:///%s' % folder)

    def view_changelog(self):
        QDesktopServices.openUrl('https://github.com/syncthing/syncthing/releases/latest')

    @QtCore.pyqtSlot()
    def handleStatusMessage(self, message):
        '''
        Handle the message from the thread used to update the status
        '''
        if message == 'OK':
            if 'Connected' in self.toolTip():
                self.setIcon(QIcon('icons/logo-ok.png'))
            else:
                message = 'No nodes connected'
        else:
            self.setIcon(QIcon('icons/logo-sync.png'))

        font = QFont()
        font.setBold(True)
        message = 'Status: %s' % unicode(message)
        if message != self.status.text():
            self.status.setText(message)
            self.status.setFont(font)
            self.setToolTip(message)
            log.info('%s' % self.status.text())

    @QtCore.pyqtSlot()
    def handleNodesMessage(self, nodes):
        '''
        Handle the message from the thread used to update the status
        '''
        connected_nodes = nodes.keys()
        connected_nodes.remove('total')

        nodes = {node['NodeID']: node['Name'] for node in syncthing_nodes}

        connected_names = [nodes[node] for node in nodes if node in connected_nodes]

        stats = syncthing.get_node_stats()
        max_length = max([len(node['Name']) for node in syncthing_nodes])

        for action in self.nodes.actions():
            name = action.text().split()[0]
            if name in connected_names:
                if not action.isEnabled():
                    log.info('Connected to %s' % name)
                    action.setText(name)
                    action.setDisabled(False)
            else:
                node_id = [node for node in nodes if nodes[node] in action.text()][0]

                last_seen = stats[node_id]['LastSeen']
                last_seen = '+'.join([last_seen.split('+')[0][:-1], last_seen.split('+')[1]]) # hack to let arrow parse it
                last_seen = arrow.get(last_seen)

                action.setText('%-*s (last seen: %s)' % (-max_length, nodes[node_id], last_seen.humanize()))
                action.setDisabled(True)

        if connected_names:
            names = ', '.join([a.text() for a in self.nodes.actions() if a.text() in connected_names])
            self.setToolTip('%s\nConnected to: %s' % (self.status.text(), names))
            self.setIcon(QIcon('icons/logo-ok.png'))
        else:
            self.setToolTip(self.status.text())
            self.setIcon(QIcon('icons/logo-not-connected.png'))
    
    @QtCore.pyqtSlot()
    def handleUpdateMessage(self, update):
        if update:
            self.update.setText('New version available!')
            self.update.triggered.connect(self.open_syncthing_web)
            self.changelog.setVisible(True)
        else:
            self.update.setText('Up to date')
            self.changelog.setVisible(False)

    @QtCore.pyqtSlot()
    def handleRecentsMessage(self, recents):
        if not recents and syncthing_repositories:
            return

        recents = [recent for recent in recents if recent['type'] == 'LocalIndexUpdated']
        recents = recents[-10:]
        folders = {repo['ID']: repo['Directory'] for repo in syncthing_repositories}

        if recents:
            # remove all actions in recents menu
            self.recents.clear()
            max_length = max([len(recent['data']['name']) for recent in recents])

        for recent in recents:
            filename = recent['data']['name']
            directory = recent['data']['repo']
            time = recent['time']
            time = '+'.join([time.split('+')[0][:-1], time.split('+')[1]]) # hack to let arrow parse it
            time = arrow.get(time).humanize()

            action = QAction('%-*s (%s)' % (-max_length, filename, time), self.recents)

            if os.path.exists(os.path.join(folders[directory], filename)):
                action.setIcon(QIcon('icons/newfile.png'))
                action.triggered.connect(lambda: self.open_dir(folders[directory]))
            else:
                action.setIcon(QIcon('icons/delfile.png'))
                folder = os.path.join(folders[directory], '.stversions')

                if os.path.exists(os.path.join(folder, filename)):
                    action.triggered.connect(lambda: self.open_dir(folder))

            self.recents.addAction(action)

    @QtCore.pyqtSlot()
    def handleReposMessage(self, repos):
        if not repos:
            return
        max_length = max([len(repo['name']) for repo in repos])

        for action in self.folders.actions():
            repo = [repo for repo in repos if repo['name'] in action.text()][0]

            if repo['diff'] > 0:
                action.setText('%-*s (%s%%)' % (-max_length, repo['name'], repo['diff']))
            else:
                action.setText('%-*s (not syncing)' % (-max_length, repo['name']))

            if repo['diff'] == 100:
                action.setIcon(QIcon('icons/synced.png'))
            else:
                action.setIcon(QIcon('icons/unsynced.png'))


if __name__ == '__main__':
    for proc in psutil.process_iter():
        try:
            if proc.name() in ('syncthing', 'syncthing.exe'):
                break
            else:
                app = 'syncthing.exe' if sys.platform == 'win32' else 'syncthing'
                psutil.Popen(app)
                break
        except psutil.AccessDenied:
            continue

    syncthing = SyncthingClient()
    syncthing_config = syncthing.get_config()
    syncthing_nodes = syncthing.get_nodes()
    syncthing_repositories = syncthing.get_repositories()

    app = QtGui.QApplication(sys.argv)
    # more readable with a monospace font
    # http://levien.com/type/myfonts/Inconsolata.otf
    app.setFont('Inconsolata')
    app.setQuitOnLastWindowClosed(False)
    style = app.style()
    # https://github.com/syncthing/syncthing/blob/master/assets/logo-32.png
    icon = QIcon('icons/logo-32.png')
    trayIcon = SystemTrayIcon(icon)

    trayIcon.show()

    sys.exit(app.exec_())