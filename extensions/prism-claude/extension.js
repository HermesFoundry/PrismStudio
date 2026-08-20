/*---------------------------------------------------------------------------
 *  Claude, as a built-in.
 *
 *  A Claude session is a terminal running the `claude` command in the folder
 *  you have open — nothing is sent anywhere on your behalf, and pointing
 *  Claude at a file types a reference into its prompt and leaves the cursor
 *  there for you to finish the sentence and press return yourself.
 *
 *  It is summoned, never resident: no session exists until you ask for one.
 *--------------------------------------------------------------------------*/
'use strict';

const vscode = require('vscode');
const path = require('path');

const TERMINAL_NAME = 'Claude';
let session = null;          // the terminal, while there is one
let statusItem = null;

function settings() {
	return vscode.workspace.getConfiguration('prismClaude');
}

function workspaceFolder() {
	const open = vscode.window.activeTextEditor?.document?.uri;
	const folder = open ? vscode.workspace.getWorkspaceFolder(open) : undefined;
	return folder ?? vscode.workspace.workspaceFolders?.[0];
}

function start() {
	if (session) {
		return session;
	}
	const config = settings();
	const command = (config.get('command') || 'claude').trim();
	const folder = workspaceFolder();
	const location = config.get('location') === 'editor'
		? { viewColumn: vscode.ViewColumn.Beside }
		: vscode.TerminalLocation.Panel;

	session = vscode.window.createTerminal({
		name: TERMINAL_NAME,
		cwd: folder?.uri?.fsPath,
		location,
		isTransient: true,
		iconPath: new vscode.ThemeIcon('sparkle')
	});
	// The command is typed rather than exec'd so that when Claude exits you are
	// left in a shell rather than with a terminal that vanishes.
	session.sendText(command, true);
	return session;
}

function showing() {
	return Boolean(session);
}

function toggle() {
	if (showing()) {
		session.dispose();
		session = null;
		sync();
		return;
	}
	start().show(false);
	sync();
}

function reference(editor, withSelection) {
	const document = editor.document;
	const folder = workspaceFolder();
	let name = document.uri.fsPath;
	if (folder) {
		const relative = path.relative(folder.uri.fsPath, name);
		if (relative && !relative.startsWith('..')) {
			name = relative;
		}
	}
	const selection = editor.selection;
	const first = selection.start.line + 1;
	const last = selection.end.line + 1;
	if (withSelection && last !== first) {
		return `@${name} lines ${first}-${last}: `;
	}
	return `@${name} line ${first}: `;
}

function pointAt(withSelection) {
	const editor = vscode.window.activeTextEditor;
	if (!editor) {
		vscode.window.showInformationMessage('Open a file first, then point Claude at it.');
		return;
	}
	const terminal = start();
	terminal.show(false);
	// sendText with addNewLine false: the line is left unsent, waiting for you
	terminal.sendText(reference(editor, withSelection), false);
	sync();
	vscode.window.setStatusBarMessage(
		'Pointed Claude at ' + path.basename(editor.document.uri.fsPath)
		+ ' — say what you want, then Enter', 4000);
}

function restart() {
	if (session) {
		session.dispose();
		session = null;
	}
	start().show(false);
	sync();
}

function sync() {
	if (!statusItem) {
		return;
	}
	if (!settings().get('statusBar')) {
		statusItem.hide();
		return;
	}
	statusItem.text = showing() ? '$(sparkle) Claude' : '$(sparkle) Claude';
	statusItem.tooltip = showing()
		? 'Close Claude (Ctrl+Shift+C)'
		: 'Open Claude (Ctrl+Shift+C)';
	statusItem.show();
}

function activate(context) {
	statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
	statusItem.command = 'prismClaude.toggle';
	context.subscriptions.push(statusItem);

	context.subscriptions.push(
		vscode.commands.registerCommand('prismClaude.toggle', toggle),
		vscode.commands.registerCommand('prismClaude.pointAtFile', () => pointAt(false)),
		vscode.commands.registerCommand('prismClaude.pointAtSelection', () => pointAt(true)),
		vscode.commands.registerCommand('prismClaude.restart', restart),
		// somebody closed the terminal by hand: forget it, so the next summon
		// starts a fresh one rather than talking to a corpse
		vscode.window.onDidCloseTerminal(closed => {
			if (closed === session) {
				session = null;
				sync();
			}
		}),
		vscode.workspace.onDidChangeConfiguration(event => {
			if (event.affectsConfiguration('prismClaude')) {
				sync();
			}
		})
	);
	sync();
}

function deactivate() {
	session = null;
}

module.exports = { activate, deactivate };
