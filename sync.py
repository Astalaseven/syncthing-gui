#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import division
import os
import sys
import time

import arrow
from python_qt_binding import QtGui, QtCore
from python_qt_binding.QtGui import *

from syncthing import SyncthingClient

# pip install arrow requests python_qt_binding PySide

class StatusThread(QtCore.QThread):
    '''
    Thread used to update the status of SyncThing
    '''
    infoRepoMessage = QtCore.Signal(object)
    statusMessage = QtCore.Signal(object)
    nodesMessage = QtCore.Signal(object)
    
    syncthing = SyncthingClient()
    config = syncthing.get_config()
    
    
    
    def run(self):
        while True:

            repos = [repo['ID'] for repo in self.config['Repositories']]
            info_repos = self.get_repos_status(repos)
            self.infoRepoMessage.emit(info_repos)
            
            status = self.get_global_status(info_repos)
            self.statusMessage.emit(status)
            
            nodes = self.get_connected_nodes()
            self.nodesMessage.emit(nodes)
            
            time.sleep(1)
            
    def get_global_status(self, repos):
        
        status = 0

        for repo in repos:
            status += repo['diff']

        status = status / len(repos)
        status = 'OK' if (status == 100) else 'syncing... (%s%%)' % status
            
        return status
        
    def get_connected_nodes(self):
        return self.syncthing.get_connections()
        
    def get_repos_status(self, repos):
        info_repos = []

        for repo in repos:
            repo_info = self.syncthing.get_repo(repo)
            if not repo_info:
                info_repo = {'name': repo, 'diff': -1}
                continue

            globalBytes = repo_info['globalBytes'] # if repo['globalBytes'] > 0 else 1
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
    
    syncthing = SyncthingClient()
    config = syncthing.get_config()
    
    def run(self):
        update = self.update_syncthing()
        self.updateMessage.emit(update)

    def update_syncthing(self):
        version = self.syncthing.get_upgrade()
        if version['newer']:
            print('INFO: New version available: %s (actually %s)' % (version['latest'], version['running']))
        else:
            print('INFO: Syncthing is up to date')

        return version['newer']

    def download_syncthing(self, version):
        QDesktopServices.openUrl('https://github.com/syncthing/syncthing/releases/tag/%s' % version)
        self.update.setText('Update')
        self.update.triggered.connect(self.update_syncthing)

class RecentsThread(QtCore.QThread):
    '''
    Thread used to update recently updated files
    '''
    recentsMessage = QtCore.Signal(object)
    
    syncthing = SyncthingClient()
    config = syncthing.get_config()
    
    def run(self):
        while True:
            events = self.syncthing.get_events()
            self.recentsMessage.emit(events)
            
            time.sleep(30)

class SystemTrayIcon(QtGui.QSystemTrayIcon):

    def __init__(self, icon, parent=None):
        QtGui.QSystemTrayIcon.__init__(self, icon, parent)

        self.syncthing = SyncthingClient()
        self.config = self.syncthing.syncthing_config
        
        self.menu = QtGui.QMenu(parent)
        
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

        ''' Status '''
        self.status = QAction('Status: unknown', self.menu)
        self.status.setStatusTip('Test')
        self.status.setToolTip('Test0')
        self.status.triggered.connect(self.open_syncthing_web)
        self.menu.addAction(self.status)
        
        ''' Folders '''
        self.folders = self.menu.addMenu('Folders')
        self.folders.setIcon(QIcon('icons/folder.png'))
        folders = {repo['ID']: repo['Directory'] for repo in self.config['Repositories']}
        for folder in folders:
            item = QAction(folder, self.folders)
            item.triggered.connect(lambda: self.open_dir(folders[folder]))
            item.setIcon(QIcon('icons/sync.png'))
            self.folders.addAction(item)

        ''' Nodes list '''
        self.nodes = self.menu.addMenu('Nodes')
        self.nodes.setIcon(QIcon('icons/node.png'))
        nodes = {node['NodeID']: node['Name'] for node in self.config['Nodes']}

        for node in nodes:
            if node != self.syncthing.get_system()['myID']:
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
        #self.menu.hovered.connect(self.loop_print)
        self.recents.activated.connect(lambda: self.open_dir(folders[folder]))

        ''' Separator '''
        self.menu.addSeparator()

        ''' Update '''
        self.update = QAction('Update', self.menu)
        self.update.triggered.connect(self.update_thread.start)
        self.menu.addAction(self.update)
        
        ''' Restart '''
        self.restart = QAction('Restart', self.menu)
        self.restart.triggered.connect(self.restart_syncthing)
        self.menu.addAction(self.restart)
        
        ''' Separator '''
        self.menu.addSeparator()

        ''' Exit button '''
        self.exitAction = QAction('&Exit', self.menu)
        self.exitAction.triggered.connect(QtGui.qApp.quit)
        self.menu.addAction(self.exitAction)
        
        self.setContextMenu(self.menu)

    # def loop_print(self):
        # self.status_thread.start()
        # while self.menu.isVisible():
            # continue
        # self.status_thread.stop()

    def open_syncthing_web(self):
        QDesktopServices.openUrl('http://localhost:8080')

    def restart_syncthing(self):
        if self.syncthing.syncthing_apikey:
            print('INFO: Restarting Syncthing...')
            self.syncthing.restart()
        else:
            msgBox = QDialog()
            msgBox = QMessageBox().information(self, 'No API key', 'Restart needs API key to be configured.' \
            '\n\nGo to \'Edit\', \'Config\' and generate an API key.')
            self.open_syncthing_web()
            
    def open_dir(self, folder):
        QDesktopServices.openUrl('file:///%s' % folder)

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
            print('INFO: %s' % self.status.text())
    
    @QtCore.pyqtSlot()
    def handleNodesMessage(self, nodes):
        '''
        Handle the message from the thread used to update the status
        '''
        connected_nodes = nodes.keys()
        connected_nodes.remove('total')

        nodes = {node['NodeID']: node['Name'] for node in self.config['Nodes']}

        connected_names = [nodes[node] for node in nodes if node in connected_nodes]
        
        stats = self.syncthing.get_node_stats()
        max_length = max([len(node['Name']) for node in self.config['Nodes']])
        
        for action in self.nodes.actions():
            name = action.text().split()[0]
            if name in connected_names:
                if not action.isEnabled():
                    print('INFO: Connected to %s' % name)
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
            self.setToolTip('%s\nConnected to: %s' % (self.status.text(), ', '.join([a.text() for a in self.nodes.actions() if a.text() in connected_names])))
            self.setIcon(QIcon('icons/logo-ok.png'))
        else:
            self.setToolTip(self.status.text())
            self.setIcon(QIcon('icons/logo-not-connected.png'))
    
    @QtCore.pyqtSlot()
    def handleUpdateMessage(self, update):
        if update:
            self.update.setText('New version available!')
            self.update.triggered.connect(lambda: self.download_syncthing(version))
        else:
            self.update.setText('Up to date')

    @QtCore.pyqtSlot()
    def handleRecentsMessage(self, recents):
        recents = [recent for recent in recents if recent['type'] == 'LocalIndexUpdated']
        recents = recents[-10:]
        folders = {repo['ID']: repo['Directory'] for repo in self.config['Repositories']}

        if recents:
            self.recents.clear()
            # for action in self.recents.actions():
                # self.recents.removeAction(action)

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
    app = QtGui.QApplication(sys.argv)
    # http://levien.com/type/myfonts/Inconsolata.otf
    app.setFont('Inconsolata')
    app.setQuitOnLastWindowClosed(False)
    style = app.style()
    # https://github.com/syncthing/syncthing/blob/master/assets/logo-512.png
    icon = QIcon('icons/logo-32.png')
    trayIcon = SystemTrayIcon(icon)

    trayIcon.show()

    sys.exit(app.exec_())