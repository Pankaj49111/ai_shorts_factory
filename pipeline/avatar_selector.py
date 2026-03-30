import os,random

def choose_avatar():
 base='assets/avatars'
 cats=[d for d in os.listdir(base) if os.path.isdir(os.path.join(base,d))]
 cat=random.choice(cats)
 files=os.listdir(os.path.join(base,cat))
 img=random.choice(files)
 return os.path.join(base,cat,img)
