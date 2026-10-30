#ifndef RECEIPTS_PLUGIN_H
#define RECEIPTS_PLUGIN_H

#include <QObject>
#include <QString>
#include <QStringList>
#include <QHash>
#include <QByteArray>
#include "receipts_interface.h"
#include "logos_api.h"
#include "logos_sdk.h"

class ReceiptsPlugin : public QObject, public ReceiptsInterface
{
    Q_OBJECT
    Q_PLUGIN_METADATA(IID ReceiptsInterface_iid FILE "metadata.json")
    Q_INTERFACES(ReceiptsInterface PluginInterface)

public:
    explicit ReceiptsPlugin(QObject* parent = nullptr);
    ~ReceiptsPlugin() override;

    QString name() const override { return "receipts"; }
    QString version() const override { return "0.1.0"; }

    Q_INVOKABLE void initLogos(LogosAPI* api);

    Q_INVOKABLE QString loadSnapshot(const QString& path) override;
    Q_INVOKABLE QString stats() override;
    Q_INVOKABLE QString searchPairs(const QString& query) override;
    Q_INVOKABLE QString searchClaims(const QString& query) override;
    Q_INVOKABLE QString pairEstimates(const QString& x, const QString& y) override;
    Q_INVOKABLE QString listReceipts() override;
    Q_INVOKABLE QString matchReceipt(const QString& query) override;
    Q_INVOKABLE bool    setSnapshotCid(const QString& cid) override;
    Q_INVOKABLE QString askStart(const QString& prompt, const QString& maxTokens) override;
    Q_INVOKABLE QString askPoll(const QString& id) override;

signals:
    void eventResponse(const QString& eventName, const QVariantList& args);

private:
    struct AskJob { QString text; QByteArray buf; bool done = false; QString error; };
    QHash<QString, AskJob> m_jobs;
    class QNetworkAccessManager* m_net = nullptr;
    int m_jobSeq = 0;
    void postAsk(const QString& id, const QString& url, const QByteArray& payload);
    bool openDatabase();
    static QStringList tokens(const QString& text);
    static QString expand(const QString& text);
};

#endif
