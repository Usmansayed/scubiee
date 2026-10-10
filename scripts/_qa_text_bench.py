import os,time
os.environ['MINI_REPO']=r'C:\Users\usman\Downloads\context-engine'
import pipeline.map_v3_helpers as mv
from pathlib import Path
mv._warm()
files=[f for f in mv._repo_files() if Path(f).suffix.lower() in mv._GREP_EXT and mv._kind_of(f) in ('code','tests')]
for _ in range(3):
    t0=time.perf_counter()
    for f in files: mv._text(f)
    print('4877x _text()', round((time.perf_counter()-t0)*1000,1),'ms')
for _ in range(3):
    t0=time.perf_counter()
    for f in files: mv._mtime(f)
    print('4877x _mtime stat', round((time.perf_counter()-t0)*1000,1),'ms')
