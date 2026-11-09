"""Senaryo Ajanı: alt başlık için seçilen süreye uygun metin, sahne listesi, başlık,
açıklama ve hashtag üretir."""
from pydantic import BaseModel

from .. import config, db, llm, voices


class Scene(BaseModel):
    narration: str  # Türkçe seslendirme metni
    visual: str  # İngilizce görsel betimlemesi (görsel modele gider)


class Script(BaseModel):
    title: str
    description: str
    hashtags: list[str]
    scenes: list[Scene]


SYSTEM = """Kısa dikey bilgi videoları (YouTube Shorts, TikTok, Instagram Reels) için \
senaryo yazıyorsun. Kanal adı: {brand}.

Uzunluk (kesin sınır):
- Seslendirme toplamı {min_words}-{max_words} kelime (yaklaşık {seconds} saniye). Bu sınırı aşma.
- {min_scenes}-{max_scenes} sahne. Her sahnenin narration'ı 1-2 kısa cümle.

Anlatım canlı ve enerjik olsun:
- İlk cümle izleyiciyi durduran bir kanca: şaşırtıcı bir bilgi veya doğrudan bir soru.
- İzleyiciye "sen" diye hitap et, konuşur gibi yaz; kısa cümleler, ünlemler ve merak uyandıran \
geçişler kullan ("Ama asıl ilginç kısım şu!", "Peki neden?"). Ders anlatır gibi değil, arkadaşına \
heyecanla anlatır gibi.
- Son sahne kısa bir kapanış veya yorumlara davet eden bir soru.
- Bilgiler doğru olsun. Emin olmadığın rakam, tarih veya alıntıyı kullanma.

Diğer alanlar:
- visual İngilizce: o sahnede ne görüneceğini ve ne olacağını kısa bir video çekimi olarak betimle. \
Görüntüde yazı, harf veya rakam olmasın. Aynı karakter/nesne birden fazla sahnede geçiyorsa her seferinde aynı şekilde tarif et.
- title en fazla 90 karakter, dikkat çekici ama tık tuzağı olmayan.
- description 1-2 cümle.
- hashtags 3-8 adet, başında # olmadan."""


def word_count(script: Script) -> int:
    return sum(len(s.narration.split()) for s in script.scenes)


def system_prompt() -> str:
    length = voices.current_length()
    min_words, max_words = length["words"]
    min_scenes = 3 if max_words <= 60 else 4
    system = SYSTEM.format(
        brand=db.get_setting("brand_name", "bilgi kanalı"),
        min_words=min_words, max_words=max_words, seconds=length["max_seconds"],
        min_scenes=min_scenes, max_scenes=min_scenes + 2,
    )
    if config.NARRATOR_NAME:
        name = config.NARRATOR_NAME
        system += (
            f"\n\nAnlatıcı: Videoyu {name} anlatıyor; meraklı, neşeli, çocuk ruhlu sevimli bir robot, "
            f"ekranın köşesinde konuşurken görünüyor. Seslendirmeyi onun ağzından birinci tekil şahısla yaz. "
            f"İlk sahnede kancadan hemen sonra kendini kısaca tanıtabilir (ör. \"Selam, ben {name.split()[0]}!\"), "
            f"ama bunu her videoda aynı kalıpla yapma. Konu robotlarla ilgiliyse kendi robot deneyiminden "
            f"esprili küçük dokunuşlar ekleyebilir. visual alanlarında {name}'u çizdirme; sahneler konuyu anlatsın."
        )
    return system


def write(subtopic_id: int) -> Script:
    sub = db.one(
        "SELECT s.title, s.angle, t.title topic, t.notes FROM subtopics s "
        "JOIN topics t ON t.id = s.topic_id WHERE s.id = ?",
        (subtopic_id,),
    )
    if sub is None:
        raise ValueError(f"Alt başlık bulunamadı: {subtopic_id}")
    system = system_prompt()
    prompt = (
        f"Ana konu: {sub['topic']}" + (f" ({sub['notes']})" if sub["notes"] else "") + "\n"
        f"Alt başlık: {sub['title']}\nAçı/kanca: {sub['angle']}\n\nBu video için senaryoyu yaz."
    )
    script = llm.structured(system=system, prompt=prompt, schema=Script, effort="high")

    max_words = voices.current_length()["words"][1]
    if word_count(script) > max_words * 1.1:
        script = llm.structured(
            system=system,
            prompt=(
                f"Bu senaryo {word_count(script)} kelime; sınır {max_words}. Anlamı ve canlılığı koruyarak "
                f"sahneleri kısalt veya birleştir, toplamı {max_words} kelimenin altına indir. "
                f"visual alanlarını değiştirme.\n\n{script.model_dump_json(indent=2)}"
            ),
            schema=Script,
            effort="medium",
        )
    return script
