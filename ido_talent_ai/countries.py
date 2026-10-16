"""Arabic country names used for nationality, owned by this app.

Nationality is a hard eligibility rule: the rule value and the applicant's declared fact must be
the same string, so the label cannot depend on framework translations (they differ between sites
and builds). Countries missing here keep their Frappe name on both sides, which still compares
correctly."""

from __future__ import annotations

COUNTRY_AR = {
	"Saudi Arabia": "السعودية",
	"United Arab Emirates": "الإمارات",
	"Kuwait": "الكويت",
	"Qatar": "قطر",
	"Bahrain": "البحرين",
	"Oman": "عُمان",
	"Yemen": "اليمن",
	"Iraq": "العراق",
	"Jordan": "الأردن",
	"Syria": "سوريا",
	"Syrian Arab Republic": "سوريا",
	"Lebanon": "لبنان",
	"Palestine, State of": "فلسطين",
	"Palestine": "فلسطين",
	"Egypt": "مصر",
	"Sudan": "السودان",
	"South Sudan": "جنوب السودان",
	"Libya": "ليبيا",
	"Tunisia": "تونس",
	"Algeria": "الجزائر",
	"Morocco": "المغرب",
	"Mauritania": "موريتانيا",
	"Somalia": "الصومال",
	"Djibouti": "جيبوتي",
	"Comoros": "جزر القمر",
	"Eritrea": "إريتريا",
	"Ethiopia": "إثيوبيا",
	"Kenya": "كينيا",
	"Uganda": "أوغندا",
	"Nigeria": "نيجيريا",
	"Ghana": "غانا",
	"Chad": "تشاد",
	"Turkey": "تركيا",
	"Türkiye": "تركيا",
	"Iran": "إيران",
	"Iran, Islamic Republic of": "إيران",
	"Afghanistan": "أفغانستان",
	"Pakistan": "باكستان",
	"India": "الهند",
	"Bangladesh": "بنغلاديش",
	"Sri Lanka": "سريلانكا",
	"Nepal": "نيبال",
	"Indonesia": "إندونيسيا",
	"Malaysia": "ماليزيا",
	"Philippines": "الفلبين",
	"Thailand": "تايلاند",
	"Myanmar": "ميانمار",
	"China": "الصين",
	"United Kingdom": "المملكة المتحدة",
	"United States": "الولايات المتحدة",
	"Canada": "كندا",
	"France": "فرنسا",
	"Germany": "ألمانيا",
}


def country_ar(name: str | None) -> str:
	"""Arabic label of a Frappe Country name (the name itself when not listed)."""
	if not name:
		return ""
	return COUNTRY_AR.get(name.strip(), name.strip())
