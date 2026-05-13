with open('tgif-v1.0.tsv', 'r') as file:
    lines = [line.strip() for line in file.readlines()]
gifs = [line.split()[0] for line in lines]
with open('gifs.txt', 'w') as file:
    file.write('\n'.join(gifs))