import wave, struct, random
w = wave.open('C:/Users/brik3/Desktop/WaveAI/apps/audiomind/tests/test_upload.wav', 'w')
w.setnchannels(1)
w.setsampwidth(2)
w.setframerate(44100)
w.writeframes(b''.join(struct.pack('<h', random.randint(-32768, 32767)) for _ in range(4410)))
w.close()
print('WAV created successfully')
