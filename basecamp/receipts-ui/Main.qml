import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

// Pramana for Logos Basecamp.
// Paste a claim; the `receipts` core module answers from its local SQLite copy of the evidence graph.
// The graph snapshot is a file published to Logos Storage: fetch it by CID, then load it.
Item {
    id: root
    width: 900
    height: 760

    readonly property color ink: "#0f1b2d"
    readonly property color muted: "#5b6778"
    readonly property color line: "#d9dee6"
    readonly property color bg: "#eef1f5"
    readonly property color panel: "#ffffff"
    readonly property color paper: "#fbfbf8"
    readonly property color accent: "#2b54d6"
    readonly property color stamp: "#c23a2c"
    readonly property color ok: "#1f7a55"
    readonly property color lower: "#2b6fd6"
    readonly property color nul: "#8a94a3"
    readonly property color higher: "#c2512c"
    readonly property string mono: "JetBrains Mono, Menlo, Consolas, monospace"

    property var info: ({})
    property var pairs: []
    property var claims: []
    property var receipt: null
    property string status: ""

    Rectangle { anchors.fill: parent; color: root.bg }

    ScrollView {
        anchors.fill: parent
        contentWidth: availableWidth
        clip: true

        ColumnLayout {
            width: parent.width
            spacing: 14

            // header
            ColumnLayout {
                Layout.fillWidth: true
                Layout.margins: 20
                Layout.bottomMargin: 0
                spacing: 2
                Text { text: "Pramana"; font.pixelSize: 28; font.weight: Font.Medium; color: root.ink }
                Text { text: "Any claim, traced to the numbers it rests on."; color: root.muted; font.pixelSize: 13 }
                Text {
                    Layout.topMargin: 6
                    text: root.info.studies ? (root.info.studies + " papers · " + root.info.estimates + " estimates · " + root.info.claims + " author claims · " + root.info.receipts + " receipts" + (root.info.cid ? "   ·   CID " + root.info.cid.substring(0, 16) + "…" : "")) : "No evidence graph loaded yet"
                    font.family: root.mono; font.pixelSize: 11; color: root.muted
                }
            }

            // snapshot loader (shown until a graph is loaded, and on demand)
            Rectangle {
                Layout.fillWidth: true
                Layout.leftMargin: 20; Layout.rightMargin: 20
                visible: !root.info.studies || loaderToggle.checked
                color: root.panel; border.color: root.line; radius: 10
                implicitHeight: loaderCol.implicitHeight + 24
                ColumnLayout {
                    id: loaderCol
                    anchors.fill: parent; anchors.margins: 12; spacing: 8
                    Text { text: "Evidence graph snapshot"; font.weight: Font.DemiBold; color: root.ink }
                    RowLayout {
                        Layout.fillWidth: true; spacing: 8
                        TextField { id: cidField; Layout.fillWidth: true; placeholderText: "Logos Storage CID of the snapshot" }
                        TextField { id: sprField; Layout.preferredWidth: 220; placeholderText: "Peer record (SPR) of a node holding it" }
                        Button { text: "Fetch"; enabled: cidField.text.length > 0; onClicked: fetchFromStorage(cidField.text.trim(), sprField.text.trim()) }
                    }
                    RowLayout {
                        Layout.fillWidth: true; spacing: 8
                        TextField { id: pathField; Layout.fillWidth: true; placeholderText: "or a local file: /path/to/receipts_snapshot.json" }
                        Button { text: "Load file"; enabled: pathField.text.length > 0; onClicked: loadFile(pathField.text.trim()) }
                    }
                    Text { text: root.status; visible: root.status.length > 0; color: root.muted; font.pixelSize: 12; wrapMode: Text.Wrap; Layout.fillWidth: true }
                }
            }

            // claim input
            Rectangle {
                Layout.fillWidth: true
                Layout.leftMargin: 20; Layout.rightMargin: 20
                color: root.panel; border.color: root.line; radius: 12
                implicitHeight: askCol.implicitHeight + 24
                ColumnLayout {
                    id: askCol
                    anchors.fill: parent; anchors.margins: 12; spacing: 8
                    Text { text: "CLAIM"; font.family: root.mono; font.pixelSize: 11; color: root.muted; font.letterSpacing: 1 }
                    TextArea {
                        id: claimField
                        Layout.fillWidth: true
                        text: "negative thinking destroys your brain"
                        font.pixelSize: 17; wrapMode: TextArea.Wrap
                        background: Item {}
                    }
                    Flow {
                        Layout.fillWidth: true; spacing: 6
                        Repeater {
                            model: ["negative thinking destroys your brain", "coffee lowers the risk of heart disease, stroke and heart failure",
                                    "avoid five or more cups of coffee to prevent stroke", "tea and coffee reduce mortality by 22%"]
                            delegate: Button { text: modelData; flat: true; font.pixelSize: 12; onClicked: { claimField.text = modelData; check() } }
                        }
                    }
                    RowLayout {
                        Button { text: "Print receipt"; highlighted: true; onClicked: check() }
                        CheckBox { id: loaderToggle; text: "Change snapshot" }
                    }
                }
            }

            // results: receipt first, evidence and claims after
            ColumnLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 20; Layout.rightMargin: 20; Layout.bottomMargin: 24
                spacing: 12

                // the receipt
                Rectangle {
                    visible: root.receipt !== null
                    Layout.alignment: Qt.AlignHCenter
                    Layout.preferredWidth: Math.min(480, parent.width)
                    color: root.paper; border.color: root.line
                    implicitHeight: rc.implicitHeight + 32
                    ColumnLayout {
                        id: rc
                        anchors.fill: parent; anchors.margins: 16; spacing: 6
                        Text { Layout.alignment: Qt.AlignHCenter; text: "PRAMANA RECEIPT"; font.family: root.mono; font.bold: true; font.letterSpacing: 3; font.pixelSize: 15; color: root.ink }
                        Text { Layout.alignment: Qt.AlignHCenter; text: root.receipt ? root.receipt.speaker + " · " + root.receipt.kind : ""; font.family: root.mono; font.pixelSize: 11; color: root.muted }
                        Text { Layout.fillWidth: true; wrapMode: Text.Wrap; font.family: root.mono; font.pixelSize: 12; color: root.ink; text: root.receipt ? "“" + root.receipt.quote + "”" : "" }
                        Text { Layout.fillWidth: true; wrapMode: Text.Wrap; font.family: root.mono; font.pixelSize: 11; color: root.muted; text: root.receipt ? "CITED: " + root.receipt.cited : "" }
                        Repeater {
                            model: root.receipt ? root.receipt.fields : []
                            delegate: RowLayout {
                                Layout.fillWidth: true; spacing: 8
                                Text { Layout.preferredWidth: 80; text: modelData[0]; font.family: root.mono; font.bold: true; font.pixelSize: 11; color: root.ink }
                                Text { Layout.fillWidth: true; Layout.preferredWidth: 1; wrapMode: Text.Wrap; text: modelData[1]; font.family: root.mono; font.pixelSize: 11; color: root.ink }
                                Text { Layout.fillWidth: true; Layout.preferredWidth: 1; wrapMode: Text.Wrap; text: modelData[2]; font.family: root.mono; font.pixelSize: 11; color: root.ink }
                                Text { Layout.preferredWidth: 120; wrapMode: Text.Wrap; text: modelData[3].replace(/_/g, " "); font.family: root.mono; font.pixelSize: 10; font.bold: modelData[3] !== "same"
                                       color: modelData[3] === "same" ? root.ok : (modelData[3] === "unverifiable" ? root.muted : root.stamp) }
                            }
                        }
                        Text {
                            Layout.alignment: Qt.AlignHCenter; Layout.topMargin: 6
                            text: distortedCount() >= 3 ? "MISREPRESENTED" : (distortedCount() >= 1 ? "OVERSTATED" : "FAITHFUL")
                            color: distortedCount() >= 1 ? root.stamp : root.ok; font.pixelSize: 16; font.bold: true; font.letterSpacing: 2; rotation: -4
                        }
                        Text { Layout.fillWidth: true; wrapMode: Text.Wrap; font.family: root.mono; font.pixelSize: 11; color: root.ink; text: root.receipt ? "WHAT THE SOURCE FOUND. " + root.receipt.found : "" }
                        Text { Layout.fillWidth: true; wrapMode: Text.Wrap; font.family: root.mono; font.pixelSize: 11; color: root.ink; text: root.receipt ? "VERDICT. " + root.receipt.verdict : "" }
                    }
                }

                Text { text: "EVIDENCE ON FILE"; font.family: root.mono; font.pixelSize: 11; color: root.muted; font.letterSpacing: 1 }
                Text { visible: root.pairs.length === 0; text: "No exposure and outcome in the graph match these words yet."; color: root.muted }
                Repeater {
                    model: root.pairs
                    delegate: Rectangle {
                        Layout.fillWidth: true
                        color: root.panel; border.color: root.line; radius: 10
                        implicitHeight: pc.implicitHeight + 20
                        ColumnLayout {
                            id: pc
                            anchors.fill: parent; anchors.margins: 10; spacing: 6
                            Text { text: modelData.x_label + "  →  " + modelData.y_label; font.pixelSize: 15; font.bold: true; color: root.ink; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Text { text: modelData.studies + " studies · " + modelData.sources + " independent sources · " + modelData.est + " estimates"; font.family: root.mono; font.pixelSize: 11; color: root.muted }
                            Row {
                                Layout.fillWidth: true; height: 10
                                property real tot: Math.max(1, modelData.lower + modelData.nul + modelData.higher + modelData.noci)
                                Rectangle { width: parent.width * modelData.lower / parent.tot; height: 10; color: root.lower }
                                Rectangle { width: parent.width * modelData.nul / parent.tot; height: 10; color: root.nul }
                                Rectangle { width: parent.width * modelData.higher / parent.tot; height: 10; color: root.higher }
                                Rectangle { width: parent.width * modelData.noci / parent.tot; height: 10; color: root.line }
                            }
                            Text { text: modelData.lower + " lower · " + modelData.nul + " no clear effect · " + modelData.higher + " higher"; font.pixelSize: 11; color: root.muted }
                        }
                    }
                }

                Text { Layout.topMargin: 8; text: "WHAT THE AUTHORS CONCLUDED"; font.family: root.mono; font.pixelSize: 11; color: root.muted; font.letterSpacing: 1 }
                Repeater {
                    model: root.claims
                    delegate: Rectangle {
                        Layout.fillWidth: true
                        color: root.panel; border.color: root.line; radius: 8
                        implicitHeight: cc.implicitHeight + 16
                        ColumnLayout {
                            id: cc
                            anchors.fill: parent; anchors.margins: 8; spacing: 3
                            Text { Layout.fillWidth: true; wrapMode: Text.Wrap; color: root.ink; font.pixelSize: 13; text: "[" + modelData.kind + "] " + modelData.text }
                            Text { Layout.fillWidth: true; wrapMode: Text.Wrap; color: root.muted; font.pixelSize: 11; text: modelData.section + " · " + modelData.title }
                        }
                    }
                }
            }
        }
    }

    // ── Logos bridge ─────────────────────────────────────────────────────
    function call(module, method, args) {
        if (typeof logos === "undefined" || !logos.callModule) { console.log("logos bridge unavailable"); return null }
        return logos.callModule(module, method, args)
    }
    // Basecamp JSON-encodes remote return values, so a QString of JSON can arrive wrapped once more.
    function parse(raw, fallback) {
        if (raw === null || raw === undefined) return fallback
        try {
            const inner = (typeof raw === "string") ? JSON.parse(raw) : raw
            return (typeof inner === "string") ? JSON.parse(inner) : inner
        } catch (e) { console.log("parse error", e, raw); return fallback }
    }
    function refreshInfo() { root.info = parse(call("receipts", "stats", []), {}) }
    function loadFile(path) {
        const r = parse(call("receipts", "loadSnapshot", [path]), {})
        root.status = r.studies ? ("Loaded " + r.studies + " papers. SHA-256 " + r.sha256) : ("Could not load: " + (r.error || "no response"))
        refreshInfo(); check()
    }
    // Fetch the snapshot from Logos Storage by CID, then load it.
    // Follows the storage module tutorial: downloadToUrl(cid, destination) with the peer record of a node holding the data.
    function fetchFromStorage(cid, spr) {
        const dest = "file:///tmp/claim_receipts_" + cid.substring(0, 12) + ".json"
        root.status = "Fetching " + cid + " from Logos Storage…"
        const r = call("storage_module", "downloadToUrl", spr.length ? [cid, dest, spr] : [cid, dest])
        console.log("storage downloadToUrl ->", r)
        call("receipts", "setSnapshotCid", [cid])
        root.status = "Download requested. When storage reports it finished, press Load file (path filled in)."
        pathField.text = dest.replace("file://", "")
    }
    function check() {
        const q = claimField.text
        root.pairs = parse(call("receipts", "searchPairs", [q]), [])
        root.claims = parse(call("receipts", "searchClaims", [q]), [])
        const r = parse(call("receipts", "matchReceipt", [q]), {})
        root.receipt = (r && r.id) ? r : null
    }
    function distortedCount() {
        if (!root.receipt) return 0
        let n = 0
        for (let i = 0; i < root.receipt.fields.length; i++) { const v = root.receipt.fields[i][3]; if (v !== "same" && v !== "unverifiable" && v !== "narrower") n++ }
        return n
    }

    Component.onCompleted: { refreshInfo(); if (root.info.studies) check() }
}
