import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from src.retrieval.tier_retrieval import TierRetrieval
t = TierRetrieval()
t.initialize_feature_index()
t.initialize_proposal_index()

catalogue = t.get_all_features_compact()
cat_words = len(catalogue.split())

results = t.feature_loader.search('GPS tracking fleet safety', k=10)
feature_ctx = ''
for r in results:
    row = r['metadata'].get('full_row', {})
    fid  = r['metadata'].get('feature_id', '')
    name = r['metadata'].get('feature_name', '')
    w    = str(row.get('What it does', ''))
    v    = str(row.get('Business Value / Impact', ''))
    s    = str(row.get('Sales Talking Point', ''))
    d    = str(row.get('Dependencies / Inputs', ''))
    feature_ctx += f'#{fid} {name} What:{w} Value:{v} Sales:{s} Deps:{d}\n'
feat_words = len(feature_ctx.split())

prop_results = t.proposal_loader.search('GPS tracking fleet safety', k=5)
prop_ctx = ''
for r in prop_results:
    if r['similarity_score'] > 0.35:
        prop_ctx += r['metadata'].get('content', '')[:600]
prop_words = len(prop_ctx.split())

schema_words = 350
total = cat_words + feat_words + prop_words + schema_words

print(f"1. Full catalogue (all 122 features): {cat_words:>5} words  ~{int(cat_words*1.3):>5} tokens  <-- BIGGEST")
print(f"2. Feature context (top 10 matches):  {feat_words:>5} words  ~{int(feat_words*1.3):>5} tokens")
print(f"3. Proposal context (top 5 chunks):   {prop_words:>5} words  ~{int(prop_words*1.3):>5} tokens")
print(f"4. Instructions + schemas:            {schema_words:>5} words  ~{int(schema_words*1.3):>5} tokens")
print(f"   -----------------------------------------------")
print(f"   TOTAL:                             {total:>5} words  ~{int(total*1.3):>5} tokens")
print()
print(f"Without full catalogue:               {total-cat_words:>5} words  ~{int((total-cat_words)*1.3):>5} tokens")
