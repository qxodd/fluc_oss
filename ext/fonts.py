fonts: list[str] = []

print('Press ctrl+C to save fonts as fonts.txt...')
while True:
    try:
        font = input('Enter font: ')
        emoji = input('Enter emoji: ')
        fonts.append(f'「{emoji}」{font}')
    except KeyboardInterrupt:
        break

with open('fonts.txt', 'wb') as file:
    for font in fonts:
        file.write((font + '\n').encode())