#ifndef RECEIPTS_INTERFACE_H
#define RECEIPTS_INTERFACE_H

#include <QObject>
#include <QString>
#include "interface.h"

// Every method callable from QML takes QString arguments (Basecamp marshals QML args as strings)
// and returns JSON text, so the UI can parse one format.
class ReceiptsInterface : public PluginInterface
{
public:
    virtual ~ReceiptsInterface() = default;

    Q_INVOKABLE virtual QString loadSnapshot(const QString& path) = 0;   // snapshot.json -> SQLite; returns counts
    Q_INVOKABLE virtual QString stats() = 0;                             // counts + snapshot hash and CID if known
    Q_INVOKABLE virtual QString searchPairs(const QString& query) = 0;   // evidence on file for a claim
    Q_INVOKABLE virtual QString searchClaims(const QString& query) = 0;  // what the papers themselves claim
    Q_INVOKABLE virtual QString pairEstimates(const QString& x, const QString& y) = 0;
    Q_INVOKABLE virtual QString listReceipts() = 0;                      // media fidelity receipts
    Q_INVOKABLE virtual QString matchReceipt(const QString& query) = 0;  // the receipt whose quote best matches, or {}
    Q_INVOKABLE virtual bool    setSnapshotCid(const QString& cid) = 0;  // remember which Logos Storage CID the data came from
};

#define ReceiptsInterface_iid "org.logos.ReceiptsInterface"
Q_DECLARE_INTERFACE(ReceiptsInterface, ReceiptsInterface_iid)

#endif
