"""The no-PR browser review checks facts without promoting guesses to proof."""

import json
import subprocess

import build_concept_deck as deck


def test_no_pr_scan_keeps_evidence_scoped():
    source = deck._JS
    rules = source[source.index("const SOURCE_RE="):source.index("async function scanRepository")]
    fixture = {
        "tree": {"truncated": False, "tree": [
            {"type": "blob", "path": "README.md"},
            {"type": "blob", "path": "src/main.py"},
            {"type": "blob", "path": "tests/test_main.py"},
        ]},
        "contents": [
            {"path": "README.md", "ok": True, "text": "This always succeeds."},
            {"path": "src/main.py", "ok": True,
             "text": "# TODO: verify\nkey = 'ghp_" + "a" * 22 + "'"},
            {"path": "tests/test_main.py", "ok": True, "text": "assert True"},
        ],
    }
    script = (rules + "\nconst data=" + json.dumps(fixture) + ";"
              "console.log(JSON.stringify(reviewSnapshot('owner/repo','main',"
              "data.tree,data.contents))); ")
    result = subprocess.run(["node", "-e", script], capture_output=True,
                            text=True, check=True)
    passes = json.loads(result.stdout)
    assert len(passes) == 4
    assert passes[0]["claims"][0]["label"] == "Proved within scope"
    assert passes[1]["claims"][0]["label"] == "Unknown"
    assert passes[2]["claims"][0]["label"] == "Proved within scope"
    assert passes[3]["claims"][0]["label"] == "Refuted"
    assert "src/main.py:2" in passes[3]["claims"][0]["evidence"]
    assert "ghp_" not in json.dumps(passes)  # witness is a location, not a token


def test_empty_merged_pr_list_routes_to_repository_scan():
    source = deck._JS
    loader = source[source.index("function parseRepo"):source.index("function setPipeline")]
    script = """
let mode,entries;
const elements={notice:{classList:{remove(){},add(){}},textContent:''},
 origin:{textContent:''},'load-repo':{disabled:false,textContent:''}};
function by(id){return elements[id]}
function refreshDigest(){}
function setStep(n){globalThis.lastStep=n}
const fetch=async url=>{
 const value=String(url);
 if(value.includes('/pulls?'))return {ok:true,json:async()=>[]};
 if(value.endsWith('/repos/o/r'))return {ok:true,json:async()=>({default_branch:'main'})};
 if(value.includes('/git/trees/'))return {ok:true,json:async()=>({truncated:false,tree:[
   {type:'blob',path:'src/main.py',size:12}]})};
 if(value.includes('raw.githubusercontent.com'))return {ok:true,text:async()=>"print('hello')"};
 throw Error('Unexpected URL '+value);
};
""" + loader + """
loadRepo('https://github.com/o/r').then(()=>console.log(JSON.stringify({
 mode,count:entries.length,step:globalThis.lastStep,notice:elements.notice.textContent})));
"""
    result = subprocess.run(["node", "-e", script], capture_output=True,
                            text=True, check=True)
    state = json.loads(result.stdout)
    assert state["mode"] == "scan"
    assert state["count"] == 4
    assert state["step"] == 0
    assert "no recent merged PRs" in state["notice"]
