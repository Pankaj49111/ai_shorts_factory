import asyncio
import edge_tts

async def list_voices():
    voices = await edge_tts.list_voices()
    en_voices = [v for v in voices if v['Locale'].startswith('en-') and 'Neural' in v['ShortName']]
    print('Available English Neural Voices:')
    for v in en_voices[:15]:
        print(f"  {v['ShortName']} - {v['Locale']} - {v['Gender']}")

asyncio.run(list_voices())
