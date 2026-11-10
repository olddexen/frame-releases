# Frame — релизы и общий каталог

- **[Releases](https://github.com/olddexen/frame-releases/releases)** — готовые APK приложения Frame для Android TV. Приложение само проверяет новые версии и обновляется.
- **Ветка `catalog`** — файл `catalog.json`: подборки и карточки фильмов для главного экрана. Его раз в 12 часов собирает GitHub Actions (`.github/workflows/catalog.yml`, скрипт `tools/build_catalog.py`), поэтому приставки не расходуют лимит запросов к API Кинопоиска.
