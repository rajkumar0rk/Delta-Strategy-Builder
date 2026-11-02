"""Fail-closed report comparison for reproducible historical legacy research.

Ignores metadata timestamps and paths; numerics compare within user tolerance.
No data downloaded and no benchmark result claimed.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path


def compare(previous:Path,current:Path,*,tolerance:float=1e-8)->list[str]:
    if not math.isfinite(tolerance) or tolerance<0:
        raise ValueError("tolerance must be finite and nonnegative")
    a=json.loads(previous.read_text(encoding="utf-8"))
    b=json.loads(current.read_text(encoding="utf-8"))
    problems=[]
    ignore={"created_at","generated_at","data_directory","result_dir","cache_hit",
            "cache_key","run_id","path"}
    def visit(x,y,path):
        if path.rsplit(".",1)[-1] in ignore:
            return
        if isinstance(x,dict) and isinstance(y,dict):
            if set(x)!=set(y):
                problems.append(f"{path}: keys changed: {sorted(set(x)^set(y))}")
            for key in sorted(set(x)&set(y)):
                visit(x[key],y[key],f"{path}.{key}")
        elif isinstance(x,list) and isinstance(y,list):
            if len(x)!=len(y):
                problems.append(f"{path}: length {len(x)} -> {len(y)}")
            for i,(left,right) in enumerate(zip(x,y)):
                visit(left,right,f"{path}[{i}]")
        elif type(x) in (int,float) and type(y) in (int,float):
            if not (math.isfinite(float(x)) and math.isfinite(float(y)) and
                    math.isclose(float(x),float(y),rel_tol=tolerance,abs_tol=tolerance)):
                problems.append(f"{path}: {x!r} -> {y!r}")
        elif x!=y:
            problems.append(f"{path}: {x!r} -> {y!r}")
    visit(a,b,"result")
    return problems


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--baseline",required=True,type=Path)
    parser.add_argument("--current",required=True,type=Path)
    parser.add_argument("--tolerance",type=float,default=1e-8)
    args=parser.parse_args()
    changes=compare(args.baseline,args.current,tolerance=args.tolerance)
    print(json.dumps({"equal":not changes,"differences":changes[:100],
                      "difference_count":len(changes)},indent=2))
    if changes:
        raise SystemExit(1)


if __name__=="__main__":
    main()
