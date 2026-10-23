# اجرای Stage 12

پچ فقط برای شاخه `integration/atlas-feature-health` با HEAD `ecab9d0` است. ابتدا Watch را در مرز چرخه متوقف کنید. ZIP پچ را در ریشه پروژه باز کنید؛ فقط فایل README، اسکریپت و پچ داخل آن خواهد بود؛ سورس و CHANGELOG با Git Patch ساخته می‌شوند.

```bash
cd /d/Hackaton/Wallex/wallex_agent_v3
conda activate shbk
bash scripts/apply_stage12_feature_recipe.sh
python -m wallex_bot.atlas_cli feature-recipe-audit --resolution 15 --top 8
python -m wallex_bot.atlas_cli feature-recipe-audit --resolution 15 --symbol USDTTMN
```

`v2_research_only_latest_window_eligible` تنها تعداد ویژگی‌های عددی دارای تعریف جدید را نشان می‌دهد و **اجازه** اجرای آن‌ها در Champion نیست. دیتابیس، RiskGate، مدل و معاملات واقعی/فرضی تغییر نمی‌کنند. در صورت وجود فایل پچ/اسکریپت قدیمی یا HEAD نادرست اسکریپت نصب متوقف می‌شود. اگر `watch` را دوباره اجرا کنید تنها نسخه قبلی مدل و سیاست را اجرا خواهد کرد.
