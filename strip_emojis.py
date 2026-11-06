import re

with open(r'C:\Users\rakes\.gemini\antigravity\brain\35c720b6-3341-4b5b-b4a0-acaef2cdcb9b\laurimate_overview.md', 'r', encoding='utf-8') as f:
    content = f.read()

# Remove emojis
import emoji
content = emoji.replace_emoji(content, replace='')

# Also remove any remaining unicode symbols commonly used as emojis that the library might miss
content = re.sub(r'[\u2600-\u26FF\u2700-\u27BF\U0001F000-\U0001FAFF]', '', content)

with open(r'd:\Laurimate\laurimate_overview.md', 'w', encoding='utf-8') as f:
    f.write(content)
