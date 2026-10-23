"""Only package audited source names; never recurse into runtime data."""
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
FILES=('main.py','worker.py','provider.py','configuration.py','metadata.yaml','_conf_schema.json','requirements.txt')

def main():
    output=ROOT/'dist';output.mkdir(exist_ok=True)
    destination=output/'astrbot_plugin_electricity.zip'
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            archive.write(ROOT/'plugin/astrbot_plugin_electricity'/name,'astrbot_plugin_electricity/'+name)
    print(destination)

if __name__=='__main__':main()
