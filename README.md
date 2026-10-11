<p align="center">
  <a href="docs/manual/navod.md">
    <img src="docs/banner.svg" alt="Český návod: Rozdělování pomocníků krok za krokem — otevřít návod" width="100%">
  </a>
</p>

# Rostering

Program, který rozděluje přihlášené pomocníky do budov, místností a rolí na
matematické soutěži [MaSo](https://maso.mff.cuni.cz/) podle toho, co si přejí.
Výsledek pak můžete ručně upravit a vyexportovat do Excelu.

Podrobný návod s obrázky najdete v [docs/manual/navod.md](docs/manual/navod.md).
Chcete-li upravovat kód, přečtěte si [CONTRIBUTING.md](CONTRIBUTING.md) (psáno
anglicky).

## Jak začít

Nepotřebujete Python ani žádný jiný program. Stačí stáhnout verzi pro váš
systém a spustit ji.

1. Otevřete [nejnovější vydání](https://github.com/Krtiiik/MaSo-Rostering/releases/latest)
   a stáhněte archiv pro svůj systém:

   | Systém | Soubor |
   |---|---|
   | Windows | `rostering-vX.Y.Z-windows-x64.zip` |
   | Linux | `rostering-vX.Y.Z-linux-x64.tar.gz` |
   | macOS (Apple silicon) | `rostering-vX.Y.Z-macos-arm64.tar.gz` |

2. Archiv rozbalte. Vznikne složka `rostering`; všechno v ní nechte pohromadě.
3. Ze složky spusťte `rostering.exe` (Windows) nebo `rostering` (Linux/macOS).
   Ve Windows stačí dvojklik.
4. V prohlížeči se otevře aplikace na adrese <http://127.0.0.1:8000>. Okno
   programu nechte při práci otevřené; když ho zavřete, aplikace přestane
   fungovat.

Programy nejsou digitálně podepsané, takže je Windows a macOS při prvním
spuštění mohou zablokovat. Co udělat hned po stažení, aby se to nestalo, je
v [návodu](docs/manual/navod.md#potíže-se-spuštěním--udělej-to-hned).

Aplikace běží v prohlížeči: používejte Chrome, Edge nebo Firefox. V Safari
nefunguje správně.

## Co aplikace umí

Šest očíslovaných záložek nahoře jde za sebou tak, jak se pracuje:

1. **Lidé** — nahrajte export z Google Formulářů s odpověďmi organizátorů
   („Načíst organizátory“) a pak pomocníků („Načíst pomocníky“). První nahrání
   vytvoří ročník.
2. **Budovy** — budovy, místnosti, kolik pomocníků která role potřebuje a kdo
   vede. Nejrychlejší je načíst tabulku „Pomocníci v místnostech“
   („Načíst konfiguraci budov“); ta dosadí i organizátory na místa vedoucích.
3. **Štítky** — označte lidi štítky a omezte, kde smějí nositelé štítku
   pracovat.
4. **Vynucené skupinky kamarádů** — skupinky, které musí skončit spolu.
5. **Parametry rozřazování** — váhy, se kterými program rozděluje.
6. **Rozdělení pomocníků** — spusťte rozdělování, pak přetahováním pomocníků
   mezi buňkami výsledek upravte a vyexportujte do Excelu.

Cokoli čeká na vaše rozhodnutí (možní vracející se pomocníci k propojení, co se
změnilo po opětovném nahrání, ...), se sbírá v panelu **K vyřízení** za tlačítkem
se seznamem v záhlaví. Pojmenované verze rozdělení se ukládají, obnovují a
mažou v levém panelu.

Nový ročník začíná bez budov. Doporučený postup je nahrát soubory v pořadí
organizátoři, pomocníci, tabulka budov „Pomocníci v místnostech“. Rozložení
budov můžete také převzít z dřívějšího ročníku (část „Rozložení budov“ při
importu z dřívějšího ročníku), nebo ho zadat ručně na záložce Budovy.

## Vaše data

Každý ročník (rok a `jaro` nebo `podzim`, např. `2026-jaro`) se ukládá sám a dá
se otevřít, přejmenovat nebo smazat v panelu **Ročníky** v levém panelu. Data
jsou ve složce `data/`, která vznikne ve složce, odkud program spouštíte — u
programu spuštěného dvojklikem je to rozbalená složka `rostering`. Jsou v ní
osobní údaje skutečných pomocníků, proto je nesdílejte ani nezveřejňujte.

Panel **Ročníky** umí také vybrané ročníky (s uloženými verzemi nebo bez nich)
vyexportovat do jednoho souboru `.zip` a takový soubor jinde naimportovat — třeba
při přechodu na jiný počítač nebo když ročník předáváte kolegovi. Než import
cokoli změní, uložené ročníky se zazálohují do `.zip` ve složce `data/backups/`.

Při přechodu na novou verzi aplikace zkopírujte svou složku `data/` vedle nové
verze.
