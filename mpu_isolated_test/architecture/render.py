"""Render a simplified functional diagram, not a physical die layout."""
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyArrowPatch

fig, ax = plt.subplots(figsize=(14, 6.5), dpi=150)
ax.set(xlim=(0, 14), ylim=(0, 6.5))
ax.axis('off')
def box(x, y, w, h, label, size=11):
    ax.add_patch(Rectangle((x, y), w, h, facecolor='white', edgecolor='black', linewidth=1.25))
    ax.text(x+w/2, y+h/2, label, ha='center', va='center', fontsize=size)
def arrow(a, b, both=False):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle='<->' if both else '-|>', mutation_scale=13, linewidth=1.2, color='black'))

ax.text(7, 6.15, 'Acelerômetro: caminhos por eixo e interface compartilhada', ha='center', fontsize=15)
ax.add_patch(Rectangle((0.2, 1.1), 10.9, 4.65, fill=False, linewidth=1.5))
ax.text(0.4, 5.48, 'MPU-6500 — esquema funcional simplificado', fontsize=11)
for axis, y in [('X', 4.15), ('Y', 2.85), ('Z', 1.55)]:
    box(0.5, y, 2.65, 0.9, f'Eixo {axis}: massa MEMS\ne leitura capacitiva')
    box(3.6, y, 1.25, 0.9, f'ADC {axis}\n16 bits')
    arrow((3.15, y+0.45), (3.6, y+0.45))
    arrow((4.85, y+0.45), (5.35, y+0.45))
box(5.35, 1.55, 2.6, 3.5, 'Condicionamento\ndo sinal\n\nRegistradores\nX, Y e Z')
box(8.45, 1.55, 2.25, 3.5, 'Interface I²C\ncompartilhada')
arrow((7.95, 3.3), (8.45, 3.3))
box(12.15, 2.55, 1.5, 1.5, 'ESP32')
arrow((10.7, 3.55), (12.15, 3.55), both=True)
arrow((12.15, 3.05), (10.7, 3.05))
ax.text(11.65, 3.77, 'SDA\ndados', ha='center', fontsize=9)
ax.text(11.65, 2.55, 'SCL\nclock', ha='center', fontsize=9)
ax.text(7, 0.74, 'Alimentação e relógio são compartilhados; suas conexões foram omitidas.', ha='center', fontsize=10)
ax.text(7, 0.37, 'Giroscópio, temperatura, FIFO e processador de movimento não estão representados.', ha='center', fontsize=10)
fig.subplots_adjust(left=0.015, right=0.985, top=0.985, bottom=0.015)
fig.savefig(Path(__file__).with_name('mpu_architecture.png'), facecolor='white')
