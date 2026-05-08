# act_9aa985d9cc18 — Josephson Coupled ODE Derivation

**action_kind**: deduction
**task**: Derive the coupled ODEs for `n_{s,1}, n_{s,2}` and `θ = φ₁ − φ₂` from the TDSE with tunneling Hamiltonian.

---

## Step 1: Two-component TDSE

The time-dependent Schrodinger equation:

$$i\hbar\frac{d}{dt}\Psi = H\Psi$$

with:

$$H = \begin{pmatrix} eV & K \\ K & -eV \end{pmatrix}, \quad
\Psi = \begin{pmatrix} |\Delta_1| e^{i\phi_1} \\ |\Delta_2| e^{i\phi_2} \end{pmatrix}$$

Writing the two components:

$$i\hbar\frac{d}{dt}\left(|\Delta_1| e^{i\phi_1}\right) = eV\,|\Delta_1| e^{i\phi_1} + K\,|\Delta_2| e^{i\phi_2} \tag{1a}$$

$$i\hbar\frac{d}{dt}\left(|\Delta_2| e^{i\phi_2}\right) = K\,|\Delta_1| e^{i\phi_1} - eV\,|\Delta_2| e^{i\phi_2} \tag{1b}$$

---

## Step 2: Express in terms of pair densities

Let:

$$a_j \equiv \sqrt{\frac{n_{s,j}}{2}} = |\Delta_j|$$

By the chain rule:

$$\frac{d}{dt}\left(a_j e^{i\phi_j}\right) = \left(\frac{da_j}{dt} + i a_j \frac{d\phi_j}{dt}\right) e^{i\phi_j}$$

Substituting:

$$i\hbar\left(\frac{da_1}{dt} + i a_1 \frac{d\phi_1}{dt}\right) e^{i\phi_1} = eV a_1 e^{i\phi_1} + K a_2 e^{i\phi_2} \tag{2a}$$

$$i\hbar\left(\frac{da_2}{dt} + i a_2 \frac{d\phi_2}{dt}\right) e^{i\phi_2} = K a_1 e^{i\phi_1} - eV a_2 e^{i\phi_2} \tag{2b}$$

Multiply (2a) by $e^{-i\phi_1}$ and (2b) by $e^{-i\phi_2}$:

$$i\hbar\frac{da_1}{dt} - \hbar a_1 \frac{d\phi_1}{dt} = eV a_1 + K a_2 e^{i(\phi_2 - \phi_1)} \tag{3a}$$

$$i\hbar\frac{da_2}{dt} - \hbar a_2 \frac{d\phi_2}{dt} = K a_1 e^{i(\phi_1 - \phi_2)} - eV a_2 \tag{3b}$$

---

## Step 3: Introduce `θ = φ₁ − φ₂` and separate real/imaginary

Define:

$$\theta \equiv \phi_1 - \phi_2$$

Then $e^{i(\phi_2 - \phi_1)} = e^{-i\theta} = \cos\theta - i\sin\theta$ and $e^{i(\phi_1 - \phi_2)} = e^{i\theta} = \cos\theta + i\sin\theta$.

**Equation (3a):**

$$i\hbar\frac{da_1}{dt} - \hbar a_1 \frac{d\phi_1}{dt} = eV a_1 + K a_2(\cos\theta - i\sin\theta)$$

Separating:

| Part | Expression |
|------|-----------|
| **Real** | $-\hbar a_1 \dfrac{d\phi_1}{dt} = eV a_1 + K a_2 \cos\theta$ |
| **Imag** | $\hbar \dfrac{da_1}{dt} = -K a_2 \sin\theta$ |

Thus:

$$\frac{da_1}{dt} = -\frac{K}{\hbar} a_2 \sin\theta \tag{4a}$$

$$\frac{d\phi_1}{dt} = -\frac{eV}{\hbar} - \frac{K}{\hbar}\frac{a_2}{a_1}\cos\theta \tag{4b}$$

**Equation (3b):**

$$i\hbar\frac{da_2}{dt} - \hbar a_2 \frac{d\phi_2}{dt} = K a_1(\cos\theta + i\sin\theta) - eV a_2$$

Separating:

| Part | Expression |
|------|-----------|
| **Real** | $-\hbar a_2 \dfrac{d\phi_2}{dt} = K a_1 \cos\theta - eV a_2$ |
| **Imag** | $\hbar \dfrac{da_2}{dt} = K a_1 \sin\theta$ |

Thus:

$$\frac{da_2}{dt} = \frac{K}{\hbar} a_1 \sin\theta \tag{4c}$$

$$\frac{d\phi_2}{dt} = \frac{eV}{\hbar} - \frac{K}{\hbar}\frac{a_1}{a_2}\cos\theta \tag{4d}$$

---

## Step 4: Convert `da_j/dt` to `dn_{s,j}/dt`

Since $a_j = \sqrt{n_{s,j}/2}$:

$$\frac{da_j}{dt} = \frac{1}{2\sqrt{n_{s,j}/2}} \cdot \frac{1}{2}\frac{dn_{s,j}}{dt} = \frac{1}{4a_j}\frac{dn_{s,j}}{dt}$$

Equivalently:

$$\frac{dn_{s,j}}{dt} = 4a_j\frac{da_j}{dt}$$

From (4a):

$$\frac{dn_{s,1}}{dt} = 4a_1\left(-\frac{K}{\hbar} a_2 \sin\theta\right) = -\frac{4K}{\hbar} a_1 a_2 \sin\theta$$

From (4c):

$$\frac{dn_{s,2}}{dt} = 4a_2\left(\frac{K}{\hbar} a_1 \sin\theta\right) = \frac{4K}{\hbar} a_1 a_2 \sin\theta$$

Now $a_1 a_2 = \sqrt{n_{s,1}/2} \cdot \sqrt{n_{s,2}/2} = \frac{1}{2}\sqrt{n_{s,1} n_{s,2}}$, giving:

$$\boxed{\frac{dn_{s,1}}{dt} = -\frac{2K}{\hbar}\sqrt{n_{s,1} n_{s,2}} \,\sin\theta} \tag{5a}$$

$$\boxed{\frac{dn_{s,2}}{dt} = +\frac{2K}{\hbar}\sqrt{n_{s,1} n_{s,2}} \,\sin\theta} \tag{5b}$$

---

## Step 5: Conservation check

$$\frac{dn_{s,1}}{dt} + \frac{dn_{s,2}}{dt} = 0$$

Total Cooper pair number is conserved — tunneling merely transfers pairs between sides.

---

## Step 6: Phase equations in terms of density ratios

From (4b) and (4d):

$$\frac{d\phi_1}{dt} = -\frac{eV}{\hbar} - \frac{K}{\hbar}\sqrt{\frac{n_{s,2}}{n_{s,1}}}\,\cos\theta \tag{6a}$$

$$\frac{d\phi_2}{dt} = +\frac{eV}{\hbar} - \frac{K}{\hbar}\sqrt{\frac{n_{s,1}}{n_{s,2}}}\,\cos\theta \tag{6b}$$

---

## Step 7: Final `dθ/dt` equation

Using $d\theta/dt = d\phi_1/dt - d\phi_2/dt$:

$$\frac{d\theta}{dt} = \left[-\frac{eV}{\hbar} - \frac{K}{\hbar}\sqrt{\frac{n_{s,2}}{n_{s,1}}}\,\cos\theta\right] - \left[\frac{eV}{\hbar} - \frac{K}{\hbar}\sqrt{\frac{n_{s,1}}{n_{s,2}}}\,\cos\theta\right]$$

$$= -\frac{2eV}{\hbar} + \frac{K}{\hbar}\left[\sqrt{\frac{n_{s,1}}{n_{s,2}}} - \sqrt{\frac{n_{s,2}}{n_{s,1}}}\right]\cos\theta$$

$$\boxed{\frac{d\theta}{dt} = -\frac{2eV}{\hbar} + \frac{K}{\hbar}\left(\sqrt{\frac{n_{s,1}}{n_{s,2}}} - \sqrt{\frac{n_{s,2}}{n_{s,1}}}\right)\cos\theta} \tag{7}$$

---

## Summary: Complete coupled ODE system

$$\boxed{\frac{dn_{s,1}}{dt} = -\frac{2K}{\hbar}\sqrt{n_{s,1}n_{s,2}}\,\sin\theta}$$

$$\boxed{\frac{dn_{s,2}}{dt} = +\frac{2K}{\hbar}\sqrt{n_{s,1}n_{s,2}}\,\sin\theta}$$

$$\boxed{\frac{d\theta}{dt} = -\frac{2eV}{\hbar} + \frac{K}{\hbar}\left(\sqrt{\frac{n_{s,1}}{n_{s,2}}} - \sqrt{\frac{n_{s,2}}{n_{s,1}}}\right)\cos\theta}$$

**Asymmetric correction term** (second term in dθ/dt): vanishes when $n_{s,1} = n_{s,2}$, recovering the standard AC Josephson relation $d\theta/dt = -2eV/\hbar$.

---

## Verification: Consistency with known Josephson limits

1. **Zero tunneling ($K \to 0$)**: $dn_{s,j}/dt = 0$ (densities constant), $d\theta/dt = -2eV/\hbar$ (phase precesses freely under bias).

2. **Symmetric densities ($n_{s,1} = n_{s,2}$)**: $d\theta/dt = -2eV/\hbar$ (standard AC Josephson), $dn_{s,1}/dt = -dn_{s,2}/dt = -(2K/\hbar)n_s\sin\theta$ (leading-order pair current with $I \propto \sin\theta$).

3. **Equilibrium with bias ($V=0$)**: Stationary points at $\sin\theta = 0$ and $\cos\theta(\sqrt{n_{s,1}/n_{s,2}} - \sqrt{n_{s,2}/n_{s,1}}) = 0$, giving $\theta = 0, \pi$ and $n_{s,1}=n_{s,2}$ as the fixed point.
