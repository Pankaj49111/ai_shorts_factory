import asyncio
import edge_tts

async def list_us_voices():
    voices = await edge_tts.list_voices()
    us_voices = [v for v in voices if v['Locale'] == 'en-US' and 'Neural' in v['ShortName']]
    print('US English Neural Voices:')
    for v in us_voices:
        print(f"  {v['ShortName']} - {v['Gender']}")

asyncio.run(list_us_voices())
