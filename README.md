# 鳴潮 Wuthering Waves — Discord 情報機器人 🌊

每週一台北時間 09:00 自動抓取「鳴潮 Wuthering Waves」最新消息,發到指定的 Discord 頻道。免費、常駐、免開電腦(GitHub Actions)。

## 安裝(只需一次)
1. 這個 repo 建好後,到 **Settings → Secrets and variables → Actions → New repository secret**
2. 新增一個 secret:
   - **Name**: `WEBHOOK`
   - **Value**: 這款遊戲頻道的 Discord Webhook 網址
3. 到 **Actions** 分頁啟用,點「每週遊戲情報 → Run workflow」測一次。
4. 之後每週一自動發送。

## 調整
- 發送時間:改 `.github/workflows/weekly-news.yml` 的 `cron`(UTC;台北 −8 小時)。
- 天數/則數:同檔案的 `DAYS_BACK` / `MAX_ITEMS`。
- 關鍵字來源:`news_bot.py` 最上面的 `GAME`。

> GitHub 排程若 repo 連續 60 天無活動會自動暫停,進去手動 Run 一次即可恢復。
