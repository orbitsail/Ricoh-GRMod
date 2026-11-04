import json,sys
d={}
for f in ['training','validation','testing']: d.update(json.load(open(sys.argv[1]+'/raw5k/meta/%s.json'%f)))
print(json.dumps(d[sys.argv[2]]))
